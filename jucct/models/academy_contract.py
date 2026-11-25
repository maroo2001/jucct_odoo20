from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class AcademyContract(models.Model):
    _name = 'academy.contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Academy Contract'
    _order = 'start_date desc, id desc'
    _rec_name = 'display_name'

    # Basic Information
    academy_id = fields.Many2one('res.partner', string="Academy", required=True, 
                                domain=[('edu_type', '=', 'academy')], tracking=True)
    contract_number = fields.Char(string="Contract Number", required=True, tracking=True)
    display_name = fields.Char(string="Contract", compute='_compute_display_name', store=True)
    
    # Contract Period
    start_date = fields.Date(string="Start Date", required=True, tracking=True)
    end_date = fields.Date(string="End Date", required=True, tracking=True)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('expired', 'Expired'),
    ], string="Status", compute='_compute_status', store=True, tracking=True, default='pending')
    
    # Contract Details
    revenue_share = fields.Float(string="Commission Rate (%)", digits=(5, 2), required=True, tracking=True)
    responsible_employee_id = fields.Many2one('res.users', string="Responsible Employee", 
                                            default=lambda self: self.env.user.id, tracking=True)
    
    # Notes and Attachments
    notes = fields.Text(string="Contract Notes", tracking=True)
    attachment_ids = fields.One2many(
        comodel_name='ir.attachment',
        inverse_name='res_id',
        domain=[('res_model', '=', 'academy.contract')],
        string="Contract Files",
    )
    
    # System fields
    is_current = fields.Boolean(string="Current Contract", compute='_compute_is_current', store=False)    
    create_date = fields.Datetime(string="Created On", readonly=True)
    write_date = fields.Datetime(string="Last Updated", readonly=True)
    
    @api.depends('contract_number', 'academy_id')
    def _compute_display_name(self):
        for record in self:
            if record.contract_number and record.academy_id:
                record.display_name = f"{record.contract_number} - {record.academy_id.name}"
            else:
                record.display_name = record.contract_number or "New Contract"
    
    @api.depends('start_date', 'end_date')
    def _compute_status(self):
        """Automatically update contract status based on current date"""
        today = date.today()
        for record in self:
            if not record.start_date or not record.end_date:
                record.status = 'pending'
            elif record.end_date < today:
                record.status = 'expired'
            elif record.start_date > today:
                record.status = 'pending'
            else:
                record.status = 'active'
    @api.depends('academy_id', 'status', 'create_date', 'write_date')
    def _compute_is_current(self):
        """Mark the most recent *active* contract as current for each record."""
        for record in self:
            if not record.academy_id:
                record.is_current = False
                continue

            # Search all active contracts for the same academy
            active_contracts = self.search([
                ('academy_id', '=', record.academy_id.id),
                ('status', '=', 'active'),
            ])

            if not active_contracts:
                record.is_current = False
                continue

            # Define a safe key function to sort contracts by create_date, write_date, and id
            def sort_key(r):
                # Use minimal datetime if None
                create_dt = r.create_date or '1970-01-01 00:00:00'
                write_dt = r.write_date or '1970-01-01 00:00:00'
                return (create_dt, write_dt, r.id)

            # Sort active contracts descending by create_date, write_date, and id
            latest_active_contract = sorted(active_contracts, key=sort_key, reverse=True)[0]

            # Set is_current True if this record is the latest active contract
            record.is_current = (record.id == latest_active_contract.id)

    
    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.start_date and record.end_date:
                if record.start_date >= record.end_date:
                    raise ValidationError(_("Contract end date must be after start date."))
    
    @api.constrains('revenue_share')
    def _check_revenue_share(self):
        for record in self:
            if record.revenue_share < 0 or record.revenue_share > 100:
                raise ValidationError(_("Commission rate must be between 0 and 100."))
    

    
