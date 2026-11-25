from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date 
import re

class Student(models.Model):
    _inherit = "res.partner"
    
    national_id = fields.Char(
    string="National ID",
    size=10,
    required=True,
    help="National ID must be unique and contain exactly 10 digits"
    )
    university_id = fields.Char(string="Student ID" ,default="N/A")
    date_of_birth = fields.Date(string="Date of Birth")
    has_confirmed_diploma = fields.Boolean(
        string='Has Confirmed Diploma Enrollment',
        compute='_compute_has_confirmed_diploma',
        store=True  
    )
    
    sessions = fields.One2many(
        'academy.session', 
        string="sessions",
        compute='_compute_student_sessions'
    )
    
    session_count = fields.Integer(compute='_compute_student_sessions')
    
    enrollment_count = fields.Integer(
        compute='_compute_enrollment_count', 
        store=True  
    )
    
    invoice_count = fields.Integer(compute='_compute_student_invoices')
    date_of_birth = fields.Date(string="Date of Birth")
    
    enrollment_line_ids = fields.One2many(
        'sale.order.line',
        compute='_compute_enrollment_lines',
        string="Enrollment Lines",
        store=False
    )
    
    enrolled_program_ids = fields.Many2many(
        'product.template',
        string="Enrolled Programs",
        compute='_compute_enrolled_programs',
        store=False,
        help="Programs this student is enrolled in"
    )
    
    enrolled_offering_ids = fields.Many2many(
        'academy.program.offering',
        string="Enrolled Offerings",
        compute='_compute_enrolled_offerings',
        store=False,
        help="Class offerings this student is enrolled in"
    )
    
    enrolled_academies_ids = fields.Many2many(
        'res.partner',
        string="Enrolled Academies",
        compute='_compute_enrolled_academies',
        store=False,
        help="Academies this student is enrolled with"
    )
    
    enrolled_programs_display = fields.Text(
        string="Program",
        compute='_compute_enrolled_programs_display',
        store=True
    )
    
    enrolled_offerings_display = fields.Text(
        string="Offering",
        compute='_compute_enrolled_offerings_display',
        store=False
    )
    
    enrolled_academies_display = fields.Text(
        string="Academy",
        compute='_compute_enrolled_academies_display',
        store=True
    )
    
    enrollment_years = fields.Char(
        string="Year",
        compute="_compute_enrollment_years",
        store=True
    )
    
    enrollment_semesters = fields.Char(
        string="Semester",
        compute="_compute_enrollment_semesters",
        store=True
    )
    
    enrollment_summary = fields.Text(
        string="Enrollment Summary",
        compute='_compute_enrollment_summary',
        store=False,
        help="Summary showing Program → Academy → Offering"
    )

    @api.depends('invoice_ids')
    def _compute_student_invoices(self):
        inv = self.env['account.move']
        for partner in self:
            partner.invoice_count = inv.search_count([
                ('is_enrollment', '=', True),
                ('partner_id', '=', partner.id),
            ])
    
    @api.depends('sale_order_ids.state', 'sale_order_ids.program_type')
    def _compute_has_confirmed_diploma(self):
        for partner in self:
            partner.has_confirmed_diploma = any(
                order.state == 'sale' and order.program_type == 'diploma'
                for order in partner.sale_order_ids
            )
    
    @api.depends('sale_order_ids', 'sale_order_ids.state')
    def _compute_enrollment_count(self):
        for record in self:
            record.enrollment_count = len(record.sale_order_ids.filtered(
                lambda so: so.state == 'sale' and so.is_enrolment
            ))
    
    @api.depends('sale_order_ids', 'sale_order_ids.state', 'sale_order_ids.order_line')
    def _compute_enrollment_lines(self):
        for partner in self:
            if partner.edu_type == 'student':
                confirmed_orders = partner.sale_order_ids.filtered(
                    lambda so: so.state == 'sale' and so.is_enrolment
                )
                partner.enrollment_line_ids = confirmed_orders.mapped('order_line').filtered(
                    lambda line: line.program_id and line.academy_id
                )
            else:
                partner.enrollment_line_ids = False

    @api.depends('enrollment_line_ids')
    def _compute_enrollment_summary(self):
        for partner in self:
            if not partner.enrollment_line_ids:
                partner.enrollment_summary = ''
                continue
            
            summary_lines = []
            for line in partner.enrollment_line_ids:
                program = line.program_id.name if line.program_id else 'N/A'
                academy = line.academy_id.name if line.academy_id else 'N/A'
                offering = line.class_offering_id.display_name if line.class_offering_id else 'N/A'
                summary_lines.append(f"• {program} → {academy} → {offering}")
            
            partner.enrollment_summary = '\n'.join(summary_lines)
    
    @api.depends('sale_order_ids', 'sale_order_ids.state', 'sale_order_ids.order_line')
    def _compute_enrolled_programs(self):
        for partner in self:
            if partner.edu_type == 'student':
                confirmed_orders = partner.sale_order_ids.filtered(
                    lambda so: so.state == 'sale' and so.is_enrolment
                )
                programs = confirmed_orders.mapped('order_line.program_id')
                partner.enrolled_program_ids = [(6, 0, programs.ids)]
            else:
                partner.enrolled_program_ids = [(5, 0, 0)]
    
    @api.depends('sale_order_ids', 'sale_order_ids.state', 'sale_order_ids.order_line')
    def _compute_enrolled_offerings(self):
        for partner in self:
            if partner.edu_type == 'student':
                confirmed_orders = partner.sale_order_ids.filtered(
                    lambda so: so.state == 'sale' and so.is_enrolment
                )
                offerings = confirmed_orders.mapped('order_line.class_offering_id')
                partner.enrolled_offering_ids = [(6, 0, offerings.ids)]
            else:
                partner.enrolled_offering_ids = [(5, 0, 0)]
    
    @api.depends('sale_order_ids', 'sale_order_ids.state', 'sale_order_ids.order_line')
    def _compute_enrolled_academies(self):
        for partner in self:
            if partner.edu_type == 'student':
                confirmed_orders = partner.sale_order_ids.filtered(
                    lambda so: so.state == 'sale' and so.is_enrolment
                )
                academies = confirmed_orders.mapped('order_line.academy_id')
                partner.enrolled_academies_ids = [(6, 0, academies.ids)]
            else:
                partner.enrolled_academies_ids = [(5, 0, 0)]
    
    @api.depends('enrolled_program_ids')
    def _compute_enrolled_programs_display(self):
        for partner in self:
            if partner.enrolled_program_ids:
                programs = partner.enrolled_program_ids.mapped('name')
                partner.enrolled_programs_display = ', '.join(programs)
            else:
                partner.enrolled_programs_display = ''
    
    @api.depends('enrolled_offering_ids')
    def _compute_enrolled_offerings_display(self):
        for partner in self:
            if partner.enrolled_offering_ids:
                offerings = partner.enrolled_offering_ids.mapped('display_name')
                partner.enrolled_offerings_display = ', '.join(offerings)
            else:
                partner.enrolled_offerings_display = ''
    
    @api.depends('enrolled_academies_ids')
    def _compute_enrolled_academies_display(self):
        for partner in self:
            if partner.enrolled_academies_ids:
                academies = partner.enrolled_academies_ids.mapped('name')
                partner.enrolled_academies_display = ', '.join(academies)
            else:
                partner.enrolled_academies_display = ''

    @api.depends('sale_order_ids.state', 'sale_order_ids.order_line.year')
    def _compute_enrollment_years(self):
        for student in self:
            year = [y for y in student.enrollment_line_ids.mapped('year') if y]
            student.enrollment_years = ', '.join(year) if year else ''

    @api.depends('sale_order_ids.state', 'sale_order_ids.order_line.semester')
    def _compute_enrollment_semesters(self):
        for student in self:
            semester = [s for s in student.enrollment_line_ids.mapped('semester') if s]
            student.enrollment_semesters = ', '.join(semester) if semester else ''

    def action_enrollments(self):
        """Open Student Enrollments in a popup filtered by this partner."""
        self.ensure_one()
        action = self.sudo().env.ref('jucct.enrollment_jucct_action').sudo().read()[0]
        action.update({
            'domain': [
                ('state', '=', 'sale'),
                ('is_enrolment', '=', True),
                ('partner_id', '=', self.id),
            ],
            'context': {
                'default_partner_id': self.id,
                'default_is_enrolment': True,
                'form_view_ref': 'jucct.enrollment_jucct_form_view',
                'default_payment_term_id': self.env.ref('jucct.payment_term_10_percent_monthly').id,
                'no_open': False,
                'show_choice': False,
            },
        })
        return action
    
    def action_invoices(self):
        """Open Student invoices in a popup filtered by this partner."""
        return {
            'name': _('Student Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('is_enrollment', '=', True),
                ('partner_id', '=', self.id),
            ],
            'context': {
                'default_partner_id': self.id,
                'default_is_enrollment': True,
                'no_open': False,
                'list_view_ref': 'jucct.view_move_list_inherit_program_fields'
            },
        }
    
    @api.depends('sale_order_ids', 'sale_order_ids.order_line')
    def _compute_student_sessions(self):
        for record in self:
            if record.edu_type == 'student':
                domain = [
                    ('state', '=', 'sale'),
                    ('is_enrolment', '=', True),
                    ('partner_id', '=', record.id),
                ]
                sale_orders = self.env['sale.order'].search(domain)
                sessions = sale_orders.mapped('order_line.class_offering_id.session_ids')
                record.sessions = sessions
                record.session_count = len(sessions)
            else:
                record.sessions = False
                record.session_count = 0
    
    def action_schedule(self):
        return {
            'name': _('Student sessions'),
            'type': 'ir.actions.act_window',
            'res_model': 'academy.session',
            'view_mode': 'list,form',
            'domain': [
                ('id', 'in', self.sessions.ids), ('record_type', '=', 'session day')
            ],
            'context': {
                'group_by': 'program_id',  
            },
        }
    
    edu_type = fields.Selection(
        selection=[("student", "Student"), ("academy", "Academy")],
        string="Type",
        store=True,
    )
    
    country_id = fields.Many2one(
        'res.country',
        string="Country",
    )
    
    country_phone_code = fields.Char(string="Country Code", readonly=True)
    
    @api.model
    def default_get(self, fields):
        res = super(Student, self).default_get(fields)
        jordan = self.env['res.country'].search([('code', '=', 'JO')], limit=1)
        if jordan:
            res['country_id'] = jordan.id
            res['country_phone_code'] = '+' + str(jordan.phone_code)
        return res

    @api.onchange('country_id')
    def _onchange_country_id(self):
        if self.country_id:
            self.country_phone_code = '+' + str(self.country_id.phone_code)

    @api.constrains('national_id', 'phone', 'email')
    def _check_field_lengths(self):
        for record in self:
            if record.national_id:
                if record.national_id and len(record.national_id) != 10 or not record.national_id.isdigit():
                    raise ValidationError(_("National ID must have exactly 10 digits."))
            if record.phone:
                if len(record.phone) != 9 or not record.phone.isdigit():
                    raise ValidationError(_("Phone number must be exactly 9 digits and contain only numbers."))

            if record.email and '@' not in record.email:
                raise ValidationError(_("Email must contain '@'."))


    @api.model_create_multi
    def create(self, vals_list):
        """التحقق من تاريخ الميلاد عند إنشاء سجل جديد"""
        for vals in vals_list:
            if vals.get('edu_type') == 'student' and not vals.get('date_of_birth'):
                raise ValidationError(_("Date of Birth is required for students."))
        return super(Student, self).create(vals_list)

    def write(self, vals):
        """التحقق من تاريخ الميلاد عند تعديل سجل"""
        for record in self:
            new_edu_type = vals.get('edu_type', record.edu_type)
            new_date_of_birth = vals.get('date_of_birth', record.date_of_birth)
            
            if new_edu_type == 'student' and not new_date_of_birth:
                raise ValidationError(_("Date of Birth is required for students."))
        
        return super(Student, self).write(vals)
            
    @api.constrains('national_id')
    def _check_national_id_unique(self):
        """Check that National ID is unique among students."""
        for record in self:
            if record.national_id and record.edu_type == 'student':
                # Search for other records with the same national_id
                existing = self.env['res.partner'].search([
                    ('national_id', '=', record.national_id),
                    ('id', '!=', record.id),
                    ('edu_type', '=', 'student'),
                ])
                if existing:
                    raise ValidationError(
                        _("A student with National ID '%s' already exists. National ID must be unique.") % record.national_id
                    )