from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date

class EducationalProduct(models.Model):
    _inherit = "product.template"

    program_type = fields.Selection([
        ('course', 'Course'),
        ('diploma', 'Diploma')
    ], string="Program Type")

    venue = fields.Selection(
        [("inside", "Inside"), ("outside", "Outside"), ("online", "Online")],
        string="Location"
    )
    is_program = fields.Boolean(string="Is Program", default=False)

    list_price = fields.Float(
        string='Sales Price',
        default=1.0,
        digits='Product Price',
        tracking=True,
        help="Program selling price",
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id.id,
    )
    def _creation_message(self):
        """Customize the creation message for programs
        For other models, fall back to the default mail.thread behavior.
        """
        self.ensure_one()

        if self._name == 'product.template' and getattr(self, 'is_program', False):
            if self.program_type == 'course':
                doc_name = _("Course Record")
                return _('%s created') % doc_name
            else:
                doc_name = _("Diploma Record")
                return _('%s created') % doc_name

        return super()._creation_message()
    @api.constrains('list_price')
    def _check_list_price(self):
        for record in self:
            if record.is_program and record.list_price < 0:
                raise ValidationError(_("Program price must be greater than 0"))
            
    approval_number = fields.Char(string="Approval Number",compute='_compute_aproval_date', store=True)
    start_date = fields.Date(string="Start Date", compute='_compute_aproval_date', store=True)
    end_date = fields.Date(string="End Date", compute='_compute_aproval_date', store=True)
    pro_read = fields.Boolean(string="Program Readonly", default=False)
    status = fields.Selection(
        [("active", "Active"), ("expired", "Expired"), ("pending", "Pending")],
        string="Program Status",
        compute='_compute_status',
        default=lambda self: "pending" if self.env.context.get('default_program_type') == 'diploma' else "active",
        store=True,
        readonly=True  
    )

    comment = fields.Text(string="Internal Notes")

    approval_ids = fields.One2many(
        'educational.approval', 'program_id', string="Approvals"
    )

    academy_id = fields.Many2one(
        'res.partner',
        string='Academy',
        domain=[('edu_type', '=', 'academy')],
    )

    session_ids = fields.One2many(
        'academy.session',
        'program_id',
        string='Sessions'
    )

    offering_ids = fields.One2many(
        'academy.program.offering', 'program_id', string="Academy Offerings"
    )
    
    offering_count = fields.Integer(
        string="Number of Offerings", compute='compute_offering_count')
    
    # NEW: Session Count
    session_count = fields.Integer(
        string='Session Count',
        compute='_compute_session_count',
        store=False
    )

    @api.depends('offering_ids')
    def compute_offering_count(self):
        for record in self:
            record.offering_count = len(record.offering_ids)

    # NEW: Compute Session Count
    @api.depends('session_ids')
    def _compute_session_count(self):
        for record in self:
            record.session_count = len(record.session_ids.filtered(lambda s: s.record_type == 'session day'))

    @api.depends('approval_ids')
    def _compute_aproval_date(self):
        for record in self:
            if record.approval_ids:
                record.start_date = record.approval_ids[-1].start_date
                record.end_date = record.approval_ids[-1].end_date
                record.approval_number = record.approval_ids[-1].approval_number
            else:
                record.start_date = False
                record.end_date = False

    @api.depends('start_date', 'end_date')
    def _compute_status(self):
        today = date.today()
        for record in self:
            if record.program_type == 'diploma':
                if record.end_date and record.end_date < today:
                    record.status = 'expired'
                elif record.start_date and record.start_date > today:
                    record.status = 'pending'
                else:
                    if record.start_date and record.end_date and record.start_date <= record.end_date:
                        record.status = 'active'
                    else:
                        record.status = 'pending'

    def cron_update_status(self):
        today = date.today()
        programs = self.search([('is_program', '=', True)])
        for record in programs:
            if record.program_type == 'diploma':
                if record.end_date and record.end_date < today:
                    record.status = 'expired'
                elif record.start_date and record.start_date > today:
                    record.status = 'pending'
                else:
                    if record.start_date and record.end_date and record.start_date <= record.end_date:
                        record.status = 'active'
                    else:
                        record.status = 'pending'
        
    def open_academy_offerings_action(self):
        self.ensure_one()
        action = self.env.ref('jucct.academy_offerings_jucct_action').sudo().read()[0]
        action['domain'] = [('program_id', '=', self.id)]
        action['context'] = {
            'default_program_id': self.id,
        }
        return action

    # NEW: Open Sessions Action with Filters
    def action_view_sessions(self):
        self.ensure_one()
        
        list_view_id = self.env.ref('jucct.academy_session_jucct_list_view').id
        form_view_id = self.env.ref('jucct.academy_session_jucct_form_view').id
        
        return {
            'name': _('Program Sessions'),
            'type': 'ir.actions.act_window',
            'res_model': 'academy.session',
            'view_mode': 'list,form',
            'views': [(list_view_id, 'list'), (form_view_id, 'form')],
            'domain': [('program_id', '=', self.id), ('record_type', '=', 'session day')],
            'context': {
                'create': True,
                'edit': False,
                'delete': False,
            },
            'target': 'current',
        }

class EducationalApproval(models.Model):
    _name = "educational.approval"
    _description = "Program Approvals"

    program_id = fields.Many2one('product.template', string="Program", required=True)
    approval_number = fields.Char(string="Approval Number", required=True)
    approval_file = fields.Binary(string="Approval File")
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")

    @api.constrains('start_date', 'end_date')
    def _check_dates_valid(self):
        for record in self:
            if record.start_date and record.end_date and record.start_date > record.end_date:
                raise ValidationError(_("Start Date cannot be after End Date."))