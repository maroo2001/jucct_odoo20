from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date, datetime



class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    is_enrolment=  fields.Boolean(related="order_id.is_enrolment" ,default=False)
    academy_id = fields.Many2one('res.partner', string="Academy")
    program_id = fields.Many2one(
        'product.template',
        string="Program",
        required=True,
        domain=[('program_type', 'in', ['course', 'diploma']), ('status', '=', 'active')],
    )
    @api.onchange('program_id')
    def _compute_program(self):
        for line in self:
            line.product_template_id = line.program_id
            product_variant = line.program_id.product_variant_id
            line.product_id = product_variant
   
    year = fields.Selection(
        [(str(y), str(y)) for y in range(fields.Date.today().year - 10, (fields.Date.today().year + 30)+1)],
        'Year'
    )
    program_type = fields.Selection(
        related="order_id.program_type",
        store=True,
        readonly=True,
    )
    semester = fields.Selection([
        ('first', 'First Semester'),
        ('second', 'Second Semester'),
        ('summer', 'Summer Semester')
    ], string="Semester")
    class_offering_id = fields.Many2one('academy.program.offering', string="Class Offering")
   

    @api.onchange('class_offering_id')
    def _onchange_class_offering_id(self):
        for line in self:
            if line.is_enrolment and line.class_offering_id and line.class_offering_id.price > 0:
                line.price_unit = line.class_offering_id.price
    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_ids')
    def _compute_amount(self):
        super(SaleOrderLine, self)._compute_amount()
        for line in self:
            if line.class_offering_id and line.class_offering_id.price > 0:
                line.update({
                    'price_subtotal': line.class_offering_id.price,
                    'price_total': line.class_offering_id.price,
                })
    offering_domain = fields.Char(
        string="Offering Domain",
        compute='_compute_offering_domain',
        store=False,
    )

    @api.depends('year','semester','order_id.program_type','academy_id','product_template_id')
    def _compute_offering_domain(self):
        for line in self:
            domain = [
                ('program_id', '=', line.product_template_id.id),
                ('status', 'in', ['active','pending']),
            ]
            if line.academy_id:
                domain.append(('academy_id','=', line.academy_id.id))

            if line.year and line.semester and line.order_id and line.order_id.program_type == 'diploma':
                year = int(line.year)
                sem = line.semester
                if sem == 'first':
                    start = date(year, 9,1)
                    end   = date(year+1, 1,31)
                elif sem == 'second':
                    start = date(year,1,1)
                    end   = date(year,5,31)
                elif sem == 'summer':
                    start = date(year,5,1)
                    end   = date(year,9,1)
                else:
                    start = end = None
                if start and end:
                    domain += [
                        ('start_date', '>=', start),
                        ('start_date', '<=', end),
                    ]
            line.offering_domain = str(domain)

    
    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'class_offering_id')
    def _compute_price_unit(self):
        super(SaleOrderLine, self)._compute_price_unit()
        for line in self:
            if  line.class_offering_id and line.class_offering_id.price > 0:
                line.price_unit = line.class_offering_id.price

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        if self.is_enrolment:
            res.update({
                'is_enrolment': self.is_enrolment,
                'academy_id': self.academy_id.id,
                'year': self.year,
                'semester': self.semester,
                'class_offering_id': self.class_offering_id.id,
            })
        return res

    @api.constrains('is_enrolment', 'order_id', 'year', 'semester')
    def _check_diploma_year_semester(self):
            """If the line is an enrolment and its sale order program is 'diploma',
            require both year and semester before saving."""
            for line in self:
                if line.is_enrolment and line.order_id and line.order_id.program_type == 'diploma':
                    if not line.year or not line.semester:
                        raise ValidationError(_("Year and Semester are required for diploma enrolments."))

        
# ============================================================
# 
# ============================================================

    @api.model_create_multi
    def create(self, vals_list):
        records = super(SaleOrderLine, self).create(vals_list)
        for record in records:
            if record.is_enrolment and record.order_id.state == 'sale' and record.academy_id and record.product_id:
                program = record.product_id.product_tmpl_id
                settlement = self.env['academy.financial.settlement'].with_context(skip_create_missing_settlements=True).create_settlement_from_enrolment(
                    record.academy_id.id,
                    program.id
                )
                if settlement:
                    # settlement._compute_program_lines()
                    settlement._compute_student_payments()
                    settlement._compute_overview()
                else:
                    existing_settlement = self.env['academy.financial.settlement'].with_context(skip_create_missing_settlements=True).search([
                        ('academy_id', '=', record.academy_id.id),
                        ('program_id', '=', program.id),
                    ], limit=1)
                    if existing_settlement:
                        # existing_settlement._compute_program_lines()
                        existing_settlement._compute_student_payments()
                        existing_settlement._compute_overview()
        return records

    def write(self, vals):
        result = super(SaleOrderLine, self).write(vals)
        if any(field in vals for field in ['order_id', 'academy_id', 'product_id', 'price_total', 'is_enrolment']):
            for record in self:
                if record.is_enrolment and record.order_id.state == 'sale' and record.academy_id and record.product_id:
                    program = record.product_id.product_tmpl_id
                    related_settlement = self.env['academy.financial.settlement'].with_context(
                        skip_create_missing_settlements=True,
                        skip_payment_validation=True 
                    ).search([
                        ('academy_id', '=', record.academy_id.id),
                        ('program_id', '=', program.id),
                    ], limit=1)
                    if related_settlement:
                        related_settlement._compute_student_payments()
                        related_settlement._compute_overview()
        return result
    def _get_conflicting_sessions(self):
        """Return list of all conflicting session pairs (current vs existing)."""
        self.ensure_one()
        conflicts = []

        if not self.is_enrolment or not self.class_offering_id or not self.order_id.partner_id:
            return conflicts

        student = self.order_id.partner_id
        offering = self.class_offering_id

        # Sessions of the current offering
        sessions = self.env['academy.session'].search_read(
            [('offering_id', '=', offering.id), ('record_type', '=', 'session day')],
            ['session_date', 'start_time', 'end_time', 'name']
        )
        if not sessions:
            return conflicts

        session_dates = [s['session_date'] for s in sessions]

        # Other enrolments of the same student (excluding this one)
        other_lines = self.env['sale.order.line'].search([
            ('is_enrolment', '=', True),
            ('order_id.partner_id', '=', student.id),
            ('id', '!=', self.id),
            ('class_offering_id', '!=', False)
        ])

        if not other_lines:
            return conflicts

        other_sessions = self.env['academy.session'].search_read([
            ('offering_id', 'in', other_lines.mapped('class_offering_id').ids), ('record_type', '=', 'session day'),
            ('session_date', 'in', session_dates)
        ], ['offering_id', 'session_date', 'start_time', 'end_time', 'name'])

        # Compare time ranges only for matching dates
        for s1 in sessions:
            for s2 in other_sessions:
                if s1['session_date'] == s2['session_date']:
                    if s1['start_time'] < s2['end_time'] and s1['end_time'] > s2['start_time']:
                        conflicts.append({
                            'date': s1['session_date'],
                            'current_name': s1['name'],
                            'other_name': s2['name'],
                            'start': s1['start_time'],
                            'end': s1['end_time'],
                        })
        return conflicts

    def action_check_conflicts(self):
        self.ensure_one()
        conflicts = self._get_conflicting_sessions()

        if not conflicts:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Conflicts Found'),
                    'message': _('This student has no conflicting session times.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        conflict_details = "\n".join([
            _("• %s (%s %s–%s)") % (
                c['date'],
                c['other_name'],
                c['start'],
                c['end']
            ) for c in conflicts
        ])

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'enrolment.conflict.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_message': _("The following scheduling conflicts were detected:\n\n%s") % conflict_details,
                'default_line_id': self.id,
            }
        }
    @api.constrains(
    'program_id', 'academy_id', 'class_offering_id',
    'year', 'semester', 'order_id', 'is_enrolment'
)
    def _check_offering_validity(self):
        for line in self:
            if not line.is_enrolment:
                continue
            
            # ---------------------------
            # 1. Academy must offer program
            # ---------------------------
            if line.academy_id:
                offered = line.academy_id.offered_program_ids.mapped('program_id')
                if line.program_id not in offered:
                    raise ValidationError(_(
                        "The selected academy does not offer the program '%s'."
                    ) % line.program_id.name)

            # ---------------------------
            # 2. Offering must match program + academy
            # ---------------------------
            offering = line.class_offering_id
            if offering:
                if offering.program_id != line.program_id:
                    raise ValidationError(_(
                        "The selected offering does not belong to the chosen program."
                    ))

                if line.academy_id and offering.academy_id != line.academy_id:
                    raise ValidationError(_(
                        "This offering belongs to academy '%s', not '%s'."
                    ) % (offering.academy_id.name, line.academy_id.name))

            # ---------------------------
            # 3. Diploma: year + semester MUST match offering date range
            # ---------------------------
            if (
                line.order_id.program_type == "diploma"
                and offering
                and line.year
                and line.semester
            ):
                year = int(line.year)
                sem = line.semester

                if sem == "first":
                    start = date(year, 9, 1)
                    end   = date(year + 1, 1, 31)
                elif sem == "second":
                    start = date(year, 1, 1)
                    end   = date(year, 5, 31)
                elif sem == "summer":
                    start = date(year, 5, 1)
                    end   = date(year, 9, 1)
                else:
                    start = end = None

                if start and end:
                    if not (offering.start_date >= start and offering.start_date <= end):
                        raise ValidationError(_(
                            "Offering '%s' does not fall in the selected year/semester."
                        ) % offering.display_name)




class SaleInvoiceLine(models.Model):
    _inherit = 'account.move.line'

    is_enrolment = fields.Boolean()
    academy_id = fields.Many2one('res.partner', string="Academy")
    year = fields.Selection(
        [(str(y), str(y)) for y in range(fields.Date.today().year - 10, (fields.Date.today().year + 30)+1)],
        'Year'
    )
    semester = fields.Selection([
        ('first', 'First Semester'),
        ('second', 'Second Semester'),
        ('summer', 'Summer Semester')
    ], string="Semester")

    class_offering_id = fields.Many2one('academy.program.offering', string="Class Offering")

class EnrolmentConflictWizard(models.TransientModel):
    _name = 'enrolment.conflict.wizard'
    _description = 'Enrollment Time Conflict Warning'

    message = fields.Text(readonly=True)
    order_id = fields.Many2one('sale.order')

    def action_continue_anyway(self):
        """Bypass the check and confirm the order."""
        self.ensure_one()
        if self.order_id:
            return self.order_id.with_context(bypass_conflict_check=True).action_confirm()
        return {'type': 'ir.actions.act_window_close'}