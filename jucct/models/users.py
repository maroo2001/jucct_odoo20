from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.exceptions import ValidationError


class EduUser(models.Model): 
    _name = "edu.user"
    _description = "Education User Manager"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    user_id = fields.Many2one('res.users', string="Related User", ondelete='cascade')
    name = fields.Char(related='user_id.name', readonly=False)
    login = fields.Char(related='user_id.login', readonly=False)
    email = fields.Char(related='user_id.email', readonly=False)
    group_ids = fields.Many2many('res.groups', string="Education Roles")
    active = fields.Boolean(related='user_id.active', readonly=False, default=True)
    password = fields.Char(string="Password", required=False)

    preferred_lang = fields.Many2one(
        'res.lang',
        string='Preferred Language',
        help="Preferred language for the created res.users. Defaults to Arabic (created if missing).",
        default=lambda self: self._default_preferred_lang(),
        domain=[('active', '=', True)],  # show only active/installed languages
    )

    # === Access Fields ===
    students_enrolment = fields.Selection([
        ('none', 'No Access'),
        ('group_student_enrolment_read', 'Can view students and enrolments only.'),
        ('group_student_enrolment_rw', 'Can view and manage students and enrolments.'),
    ], string='STUDENT / ENROLMENT ACCESS', default='none', store=True)

    students_enrolment_own_records = fields.Selection([
        ('all', 'ALL Records'),
        ('group_see_and_edit_own_students_only', 'Only the records they created'),
    ], string='STUDENT VISIBILITY', default='all', store=True)

    academy_trainer = fields.Selection([
        ('none', 'No Access'),
        ('group_academy_trainer_read', 'Can view academies and trainers.'),
        ('group_academy_trainer_rw', 'Can view/create/update academies and trainers but not their contracts.'),
        ('group_academy_trainer_contract', 'Can manage contracts for academies and trainers.'),
    ], string='ACADEMIES / TRAINERS ACCESS', default='none', store=True)

    course_offering = fields.Selection([
        ('none', 'No Access'),
        ('group_course_offering_read', 'Can view Program and offerings only.'),
        ('group_course_offering_rw', 'Can create and edit Programs and offerings.'),
    ], string='Programs / Offerings Access', default='none', store=True)

    reports_analytics = fields.Selection([
        ('none', 'No Access'),
        ('group_reports', 'Can access reports and charts'),
    ], string='REPORTS ACCESS', default='none', store=True)

    dashboard_analytics = fields.Selection([
        ('none', 'No Access'),
        ('group_dashboard', 'Can access dashboard'),
    ], string='DASHBOARD ACCESS', default='none', store=True)

    financial_analytics = fields.Selection([
        ('none', 'No Access'),
        ('group_financial_analytics', 'Can access invoices and settlements'),
    ], string='FINANCIAL ACCESS', default='none', store=True)

    user_management = fields.Selection([
        ('none', 'No Access'),
        ('group_user_management', 'Can create and manage system users.'),
    ], string='USER MANAGEMENT', default='none', store=True)


    # ======================================================================
    # GROUP SYNC LOGIC
    # ======================================================================
    def _get_selected_groups(self, vals=None):
        """Collect all selected groups from form values and return record IDs."""
        vals = vals or {}
        group_xml_ids = []

        # Primary access-level fields
        for field in [
            'students_enrolment', 'academy_trainer', 'course_offering',
            'reports_analytics', 'financial_analytics', 'dashboard_analytics',
            'user_management'
        ]:
            xml_id = vals.get(field) or (self[field] if self else False)
            if xml_id and xml_id != 'none':
                group_xml_ids.append(f"jucct.{xml_id}")

        # Student visibility rule group (own/all)
        xml_id_own = vals.get('students_enrolment_own_records') or (self.students_enrolment_own_records if self else False)
        if xml_id_own and xml_id_own != 'all':
            group_xml_ids.append(f"jucct.{xml_id_own}")

        # Resolve all to real group IDs using sudo to avoid access issues
        group_records = []
        for xml in group_xml_ids:
            try:
                grp = self.env.ref(xml)
                if grp:
                    group_records.append(grp.sudo().id)
            except (ValueError, Exception):
                pass

        return group_records


    # ======================================================================
    # CREATE / WRITE
    # ======================================================================
    @api.model_create_multi
    def create(self, vals_list):
        """Create linked res.users with the correct access groups and preferred language."""
        base_group_id = self.env.ref('base.group_user').with_user(SUPERUSER_ID).id
        for vals in vals_list:
            group_ids = self._get_selected_groups(vals)

            # determine preferred language code (ensure Arabic exists if not provided)
            if vals.get('preferred_lang'):
                pref_lang = self.env['res.lang'].with_user(SUPERUSER_ID).browse(vals.get('preferred_lang'))
            else:
                pref_lang = self._get_or_create_arabic_lang()
            preferred_code = pref_lang.code if pref_lang else False

            # Create partner explicitly as SUPERUSER to avoid ACL issues during implicit partner creation
            Partner = self.env['res.partner'].with_user(SUPERUSER_ID)
            partner_vals = {
                'name': vals.get('name') or vals.get('login') or 'New user',
                'email': vals.get('email') or False,
            }
            partner = Partner.create(partner_vals)

            user_vals = {
                'name': vals.get('name'),
                'login': vals.get('login'),
                'email': vals.get('email'),
                'lang': preferred_code or False,
                'partner_id': partner.id,
                # Odoo 19+: res.users.groups_id was renamed group_ids
                'group_ids': [(6, 0, group_ids + [base_group_id])],
            }

            # create the res.users as SUPERUSER_ID to avoid ACL blocks
            Users = self.env['res.users'].with_user(SUPERUSER_ID)
            user = Users.with_context(no_reset_password=True, create_user=False).create(user_vals)

            if vals.get('password'):
                user.with_user(SUPERUSER_ID).with_context(no_reset_password=True).write({'password': vals['password']})

            vals['user_id'] = user.id
        return super().create(vals_list)

    def write(self, vals):
        """Update related res.users when group-related fields change and sync preferred language."""
        res = super(EduUser, self).write(vals)
        base_group_id = self.env.ref('base.group_user').with_user(SUPERUSER_ID).id
        for rec in self:
            if rec.user_id:
                group_ids = rec._get_selected_groups(vals)
                # write user as SUPERUSER_ID (ensures any partner changes are allowed)
                rec.user_id.with_user(SUPERUSER_ID).write({
                    'group_ids': [(6, 0, group_ids + [base_group_id])],
                })
                # sync preferred language if changed
                if vals.get('preferred_lang'):
                    lang_rec = self.env['res.lang'].with_user(SUPERUSER_ID).browse(vals.get('preferred_lang'))
                    if not lang_rec.exists():
                        lang_rec = self._get_or_create_arabic_lang()
                    if lang_rec and lang_rec.code:
                        rec.user_id.with_user(SUPERUSER_ID).write({'lang': lang_rec.code})
        return res

    def action_send_reset_email(self):
        """Send custom invitation/reset password email using Jadara template."""
        template = self.env.ref('jucct.jadara_user_invite_email')
        for record in self:
            if record.user_id:
                template.send_mail(record.user_id.id, force_send=True)

    def _get_or_create_arabic_lang(self):
            """Safely get or create Arabic language record (ar_001)."""
            Lang = self.env['res.lang'].with_user(SUPERUSER_ID).sudo()

            lang = Lang.search([('code', 'in', ['ar_001', 'ar'])], limit=1)
            if lang:
                return lang

            vals = {
                'code': 'ar_001',
                'name': 'Arabic',
                'direction': 'rtl',
                'date_format': '%d/%m/%Y',
                'time_format': '%H:%M:%S',
                'decimal_point': '.',
                'thousands_sep': ',',
                'grouping': '[]',
                'week_start': '7',
                'url_code': 'ar_001',
                'active': True,
            }

            try:
                with self.env.cr.savepoint():
                    return Lang.create(vals)
            except Exception:
                return Lang.search([('code', 'in', ['ar_001', 'ar'])], limit=1)

    def _default_preferred_lang(self):
        lang = self.env['res.lang'].sudo().search([('code', 'in', ['ar_001', 'ar'])], limit=1)
        if lang:
            return lang.id
        lang = self._get_or_create_arabic_lang()
        return lang.id if lang else False
