from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# ============================================================
# Financial Settlement Model -
# ============================================================
class AcademyFinancialSettlement(models.Model):
    _name = "academy.financial.settlement"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Financial Settlement for Academy"

    academy_id = fields.Many2one(
        "res.partner",
        string="Academy",
        required=True,
        domain=[('edu_type', '=', 'academy')],
        options="{'no_create': True, 'no_create_edit': True, 'no_quick_create': True}"
    )
    program_id = fields.Many2one(
        'product.template',
        string="Program",
        required=True,
        ondelete='restrict',
        domain="[('program_type', 'in', ['course', 'diploma'])]",  # ← CHANGED THIS LINE
        options="{'no_create': True, 'no_create_edit': True, 'no_quick_create': True}"
    )
    offering_id = fields.Many2one(
        'academy.program.offering',
        string="Program Offering",
    )
    settlement_date = fields.Date(
        string="Settlement Date",
        default=fields.Date.context_today,
    )
    invoice_number = fields.Char(
        string="Invoice Number", 
        readonly=True, 
        copy=False
    )

    display_name = fields.Char(
        string="Settlement Name",
        compute="_compute_display_name",
        store=True
    )
    program_price = fields.Float(
        string="Program Price",
        compute="_compute_program_price",
        store=True,
        readonly=True
    )
    settlement_status = fields.Selection([
        ('draft', 'Draft'),
        ('paid', 'Confirmed')
    ], string="Settlement Status", default='draft', compute='_compute_settlement_status', store=True)
    is_manually_paid = fields.Boolean(string="Manually Marked as Paid", default=False)

    total_students = fields.Integer(
        string="Total Enrolled Students",
        compute="_compute_overview",
        store=True
    )
    active_students = fields.Integer(
        string="Active/Completed Students",
        compute="_compute_overview",
        store=True
    )
    total_paid_amount = fields.Monetary(
        string="Total Paid Amount",
        compute="_compute_overview",
        store=True,
        currency_field='currency_id'
    )
    academy_share = fields.Monetary(
        string="Academy Share",
        compute="_compute_overview",
        store=True,
        currency_field='currency_id'
    )
    center_share = fields.Monetary(
        string="Center Share",
        compute="_compute_overview",
        store=True,
        currency_field='currency_id'
    )

    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_invoice_count'
    )
    student_count = fields.Integer(
        string='Student Count',
        compute='_compute_student_count'
    )

    currency_id = fields.Many2one(
        'res.currency', 
        default=lambda self: self.env.company.currency_id
    )
    invoice_ids = fields.One2many(
        'account.move',
        'settlement_id',
        string='Invoices'
    )
    student_payment_ids = fields.One2many(
        "academy.student.payment",
        "settlement_id",
        "Student Payments",
        compute="_compute_student_payments",
        store=True,
        readonly=False
    )

    commission_rate_percent = fields.Float(
        string="Commission Rate %",
        compute="_compute_commission_rate_percent",
        store=True,
        readonly=True
    )
    is_center_settlement = fields.Boolean(
        string="Is Center Settlement",default=False)
    
    settled_offering_ids = fields.Many2many(
        'academy.program.offering',
        compute='_compute_settled_offering_ids',
        store=False
    )

    @api.depends('offering_id')
    def _compute_settled_offering_ids(self):
        for record in self:
            settled_ids = self.env['academy.financial.settlement'].search([
                ('settlement_status', '=', 'paid'),
                ('offering_id', '!=', False)
            ]).mapped('offering_id').ids
            record.settled_offering_ids = [(6, 0, settled_ids)]
    
    # ============================================================
    # Compute Methods
    # ============================================================
    @api.depends('academy_id', 'program_id', 'offering_id')
    def _compute_program_price(self):
        for rec in self:
            if rec.offering_id and rec.offering_id.price:
                rec.program_price = rec.offering_id.price
            elif rec.program_id:
                rec.program_price = rec.program_id.list_price
            else:
                rec.program_price = 0.0

    @api.depends('academy_id', 'program_id', 'offering_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.academy_id and rec.offering_id:
                rec.display_name = f"{rec.academy_id.name} - {rec.offering_id.display_name}"
            elif rec.academy_id and rec.program_id:
                rec.display_name = f"{rec.academy_id.name} - {rec.program_id.name}"
            else:
                rec.display_name = _("New Settlement")

    @api.depends('academy_id.revenue_share')
    def _compute_commission_rate_percent(self):
        for rec in self:
            rec.commission_rate_percent = rec.academy_id.revenue_share or 0.0

    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids)

    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_payment_ids.mapped('student_id'))

    @api.depends('invoice_ids', 'invoice_ids.state', 'invoice_ids.payment_state', 'is_manually_paid')
    def _compute_settlement_status(self):
        for rec in self:
            if rec.is_manually_paid or rec.is_center_settlement:
                rec.settlement_status = 'paid'
            elif rec.invoice_ids and any(inv.payment_state == 'paid' for inv in rec.invoice_ids):
                rec.settlement_status = 'paid'
            else:
                rec.settlement_status = 'draft'

    @api.depends('academy_id', 'program_id', 'offering_id', 'academy_id.revenue_share', 'program_price')
    def _compute_student_payments(self):
        for rec in self:
            rec.student_payment_ids = [(5, 0, 0)]
            if not rec.academy_id or not rec.program_id:
                continue

            enrolments = self.env['sale.order.line'].with_context(skip_create_missing_settlements=True).search([
                ('academy_id', '=', rec.academy_id.id),
                ('product_id.product_tmpl_id', '=', rec.program_id.id),
                ('class_offering_id', '=', rec.offering_id.id),
                ('is_enrolment', '=', True),
                ('order_id.state', '=', 'sale'),
            ])

            payments_dict = {}
            for line in enrolments:
                student = line.order_id.partner_id
                order = line.order_id
                
                if student.id not in payments_dict:
                    is_withdrawn = order.enrolment_status == 'withdrawn'
                    withdrawal_fine = order.withdrawal_fine if order.apply_fine else 0.0
                    payments_dict[student.id] = {
                        'student_id': student.id,
                        'program_id': line.product_id.product_tmpl_id.id,
                        'total_paid': 0.0,
                        'penalty_paid': 0.0,
                        'is_withdrawn': is_withdrawn,
                        'penalty_amount': withdrawal_fine,
                        'order_id': order.id
                    }
                
                invoices = order.invoice_ids.filtered(lambda i: i.state in ('posted', 'paid'))
                
                for invoice in invoices:
                    invoice_paid_amount = invoice.amount_total - invoice.amount_residual

                    is_fine_invoice = order.apply_fine
                    
                    if is_fine_invoice:
                        payments_dict[student.id]['penalty_paid'] += invoice_paid_amount
                        payments_dict[student.id]['total_paid'] += invoice_paid_amount
                    else:
                        payments_dict[student.id]['total_paid'] += invoice_paid_amount

            commission_percent = rec.commission_rate_percent or 0.0
            payments = []
            for student_data in payments_dict.values():
                total_paid = student_data['total_paid']
                academy_share = total_paid * (commission_percent / 100.0)
                center_share = (total_paid - academy_share) + withdrawal_fine

                payments.append((0, 0, {
                    'student_id': student_data['student_id'],
                    'program_id': student_data['program_id'],
                    'total_paid': student_data['total_paid'],
                    'penalty_paid': student_data['penalty_paid'],
                    'is_withdrawn': student_data['is_withdrawn'],
                    'penalty_amount': student_data['penalty_amount'],
                    'academy_share': academy_share,
                    'center_share': center_share,
                    'sale_order_id': student_data['order_id'],
                }))

            rec.student_payment_ids = payments

    @api.depends(
        'student_payment_ids', 
        'student_payment_ids.total_paid', 
        'student_payment_ids.penalty_paid', 
        'student_payment_ids.is_withdrawn', 
        'student_payment_ids.academy_share', 
        'student_payment_ids.center_share'
    )
    def _compute_overview(self):
        for rec in self:
            total_paid = total_academy = total_center = 0.0
            active_students = 0
            
            for payment in rec.student_payment_ids:
                total_paid += payment.total_paid
                total_academy += payment.academy_share
                total_center += payment.center_share
                if not payment.is_withdrawn:
                    active_students += 1
                    
            rec.total_students = len(rec.student_payment_ids)
            rec.active_students = active_students
            rec.total_paid_amount = total_paid
            rec.academy_share = total_academy
            rec.center_share = total_center

    # ============================================================
    # Actions 
    # ============================================================
    def action_view_invoices(self):
        self.ensure_one()
        
        commission_percent = self.commission_rate_percent or 0.0
        academy_share = self.total_paid_amount * (commission_percent / 100.0)
        
        existing_invoice = self.invoice_ids.filtered(lambda i: i.state in ('draft', 'posted'))
        
        if existing_invoice:
            for invoice in existing_invoice:
                for line in invoice.invoice_line_ids:
                    if line.product_id == self.program_id.product_variant_id:
                        line.price_unit = academy_share
            invoice_to_open = existing_invoice[0]
        else:
            invoice_to_open = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.academy_id.id,
                'settlement_id': self.id,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': [(0, 0, {
                    'product_id': self.program_id.product_variant_id.id if self.program_id.product_variant_id else False,
                    'name': f"Financial Settlement - {self.program_id.name} - {self.academy_id.name}",
                    'quantity': 1,
                    'price_unit': academy_share,
                })],
            })
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice_to_open.id,
            'target': 'current',
        }

    def action_open_student_payments(self):
        self.ensure_one()
        tree_view_id = self.env.ref('jucct.view_academy_student_payment_list').id
        form_view_id = self.env.ref('jucct.view_academy_student_payment_form').id
        
        action = {
            'type': 'ir.actions.act_window',
            'name': f'Student Payments - {self.display_name}',
            'res_model': 'academy.student.payment',
            'view_mode': 'list,form',
            'views': [(tree_view_id, 'list'), (form_view_id, 'form')],
            'domain': [('settlement_id', '=', self.id)],
            'context': {
                'default_settlement_id': self.id, 
                'default_academy_id': self.academy_id.id, 
                'create': False, 
                'edit': False
            },
            'target': 'current',
        }
        
        return action

    def action_print_invoice(self):
        self.ensure_one()
        return self.env.ref('jucct.academy_financial_settlement_report').report_action(self)

    def action_mark_as_paid(self):
        """Mark the settlement as paid manually"""
        self.ensure_one()
        
        if self.offering_id and self.offering_id.end_date:
            today = fields.Date.today()
            if self.offering_id.end_date > today:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Cannot Confirm'),
                        'message': _("Cannot confirm settlement. The program offering has not ended yet. End date: {}").format(self.offering_id.end_date or ''),
                        'type': 'info',   
                        'sticky': False,  
                        'duration': 3000, 
                    }
                }
        
        if self.settlement_status == 'draft':
            self.write({'is_manually_paid': True})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Settlement has been marked as paid.'),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('Settlement is already marked as paid.'),
                    'type': 'warning',
                }
            }
    
    @api.constrains('student_payment_ids')
    def _check_student_payments(self):
        for rec in self:
            if self.env.context.get('skip_payment_validation'):
                continue
            if rec.is_center_settlement :
                continue
            if not rec.student_payment_ids:
                raise ValidationError(_("A financial settlement must include at least one student payment."))

    @api.model_create_multi
    def create(self, vals_list):
        # Check for existing confirmed settlements for the same offering
        for vals in vals_list:
            if vals.get('offering_id'):
                existing_settlement = self.search([
                    ('offering_id', '=', vals['offering_id']),
                    ('settlement_status', '=', 'paid')  # Assuming 'paid' means confirmed
                ], limit=1)
                if existing_settlement:
                    raise ValidationError(_("A confirmed settlement already exists for this offering."))

        return super().create(vals_list)

# ============================================================
# Student Payment Model
# ============================================================
class AcademyStudentPayment(models.Model):
    _name = "academy.student.payment"
    _description = "Student Payment Detail"

    settlement_id = fields.Many2one(
        "academy.financial.settlement", 
        string="Financial Settlement", 
        ondelete="cascade"
    )
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id)
    student_id = fields.Many2one(
        "res.partner", 
        string="Student", 
        required=True
    )
    program_id = fields.Many2one(
        "product.template", 
        string="Program"
    )
    total_paid = fields.Monetary(
        string="Paid Amount", 
        required=True
    )
    
    is_withdrawn = fields.Boolean(
        string="Withdrawn"
    )
    penalty_amount = fields.Monetary(
        string="Penalty Amount", currency_field='currency_id'
    )
    academy_share = fields.Monetary(
        string="Academy Share", currency_field='currency_id'
    )
    center_share = fields.Monetary(
        string="Center Share", currency_field='currency_id'
    )

    penalty_paid = fields.Monetary(
        string="Penalty Paid", 
        default=0.0, currency_field='currency_id'
    )
    sale_order_id = fields.Many2one(
        "sale.order", 
        string="Sale Order", 
        readonly=True
    )

    offering_id = fields.Many2one(
        'academy.program.offering',
        string="Program Offering",
        domain="[('academy_id', '=', academy_id), ('program_id', '=', program_id), ('status', '=', 'active')]",
        options="{'no_create': True, 'no_create_edit': True, 'no_quick_create': True}"
    )

    currency_id = fields.Many2one(
        'res.currency', 
        default=lambda self: self.env.company.currency_id
    )

    # ============================================================
    # 
    # ============================================================
    def write(self, vals):
        result = super(AcademyStudentPayment, self).write(vals)
        
        settlements_to_update = self.mapped('settlement_id')
        if settlements_to_update:
            settlements_to_update._compute_overview()
        
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for settlement in records.settlement_id:
            settlement._compute_overview()
        return records
