from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date 
import re
class academy(models.Model):
    _inherit = "res.partner"
    #academy 
    pro_read = fields.Boolean(string="Program Readonly", default=False)
    # Academy-specific fields
    # General Information
    contact_person = fields.Char(string="Contact Person", tracking=True)
    contract_ids = fields.One2many('academy.contract', 'academy_id', string="Contracts")
    current_contract_id = fields.Many2one('academy.contract', compute='_compute_current_contract', store=True)

    # Contract Information - Now handled by academy.contract model
     # Contract Information
    contract_start_date = fields.Date(string="Contract Start Date", tracking=True)
    contract_end_date = fields.Date(string="Contract End Date", tracking=True)
    contract_status = fields.Selection([
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('pending', 'Pending')
    ], string="Contract Status", compute='_compute_contract_status', store=True, tracking=True)
    revenue_share = fields.Float(string="Commission Rate (%)", digits=(5, 2), 
                                 compute='_compute_current_contract_data', store=True, tracking=True)
    responsible_employee_id = fields.Many2one('res.users', string="Responsible Employee", 
                                            compute='_compute_current_contract_data', store=True, tracking=True)
    contract_end_date = fields.Date(string="Contract End Date", 
                                  compute='_compute_current_contract_data', store=True)
    
    # Financial Information
    bank_name = fields.Char(string="Bank Name", tracking=True)
    bank_iban = fields.Char(string="IBAN", tracking=True)
    payment_term_id = fields.Many2one(
    'account.payment.term',
)
    settlement_count = fields.Integer(
        string="Settlements Count",
        compute="_compute_settlement_count"
    )

        # Notes and Attachments - Now handled by academy.contract model
    academy_notes = fields.Text(string="General Notes", help="General notes about the academy")
    
    programs_count = fields.Integer(string="Programs Count", compute='_compute_programs_count')
    academy_students_count = fields.Integer(string="Students Count", compute='_compute_academy_students')
    academy_invoices_count = fields.Integer(string="Invoices Count", compute='_compute_academy_invoices_count')
    academy_session_count = fields.Integer(
        string='Academy Session Count',
        compute='_compute_academy_session_count'
    )
    offered_program_ids = fields.One2many(
        'academy.program.offering', 'academy_id', string="Offered Programs")
    student_ids = fields.One2many(
        'res.partner', string="Students" ,compute='_compute_academy_students')


           # Academy-related fields and methods
    academy_program_count = fields.Integer(
        string='Programs Count',
        compute='_compute_academy_program_count'
    )
    @api.depends()
    def _compute_program_count(self):
        """Count programs where this trainer teaches (has sessions)"""
        for trainer in self:
            if trainer.is_trainer:
                # Count distinct programs from sessions
                sessions = self.env['academy.session'].search([
                    ('trainer_id', '=', trainer.id)
                ])
                trainer.program_count = len(sessions.mapped('program_id'))
            else:
                trainer.program_count = 0
                
    @api.depends('offered_program_ids')
    def _compute_academy_program_count(self):
        for partner in self:
            partner.academy_program_count = len(set(partner.offered_program_ids.program_id))  

    @api.constrains('bank_iban')
    def _check_iban(self):
        """Validate IBAN format and checksum"""
        for record in self:
            if record.bank_iban:
                iban = record.bank_iban.replace(' ', '').upper()
                
                # Check basic format (JO followed by 24 digits for Jordan)
                if not re.match(r'^JO\d{2}[A-Z]{4}\d{18}$', iban):
                    raise ValidationError(_('Invalid IBAN format. For Jordan, IBAN should be: JO + 2 digits + 4 letters + 18 digits'))
                
                # Move first 4 characters to end
                iban = iban[4:] + iban[:4]
                
                # Convert letters to numbers (A=10, B=11, etc)
                iban_digits = ''
                for char in iban:
                    if char.isalpha():
                        iban_digits += str(10 + ord(char) - ord('A'))
                    else:
                        iban_digits += char
                
                # Check if it's valid (mod-97 operation)
                if int(iban_digits) % 97 != 1:
                    raise ValidationError(_('Invalid IBAN checksum. Please verify the number.'))
    @api.onchange('bank_iban')
    def _onchange_bank_iban(self):
        """Format IBAN with spaces for readability"""
        if self.bank_iban:
            # Remove existing spaces and convert to uppercase
            iban = self.bank_iban.replace(' ', '').upper()
            # Format with spaces every 4 characters
            self.bank_iban = ' '.join(iban[i:i+4] for i in range(0, len(iban), 4))

    


    def _compute_academy_session_count(self):
        """Count sessions for this academy"""
        for partner in self:
            if partner.edu_type == 'academy':
                partner.academy_session_count = self.env['academy.session'].search_count([
                    ('academy_id', '=', partner.id),
                    ('record_type', '=', 'session day')
                ])
            else:
                partner.academy_session_count = 0

    def action_academy_sessions(self):
        """Open Academy Sessions with custom views"""
        self.ensure_one()
        
        # Get view IDs
        list_view_id = self.env.ref('jucct.academy_session_jucct_list_view').id
        form_view_id = self.env.ref('jucct.academy_session_jucct_form_view').id
        
        return {
            'name': _('Academy Sessions'),
            'type': 'ir.actions.act_window',
            'res_model': 'academy.session',
            'view_mode': 'list,form',
            'views': [(list_view_id, 'list'), (form_view_id, 'form')],
            'domain': [('academy_id', '=', self.id), ('record_type', '=', 'session day')],
            'context': {'default_academy_id': self.id,
                        'group_by': ['program_id', 'offering_id'],
                        },
            'target': 'current',
        }
    @api.depends('contract_ids.status', 'contract_ids.start_date', 'contract_ids.end_date')
    def _compute_contract_status(self):
        """Get contract status prioritizing active contracts over future contracts"""
        today = date.today()
        for record in self:
            if record.edu_type == 'academy':
                active_contracts = record.contract_ids.filtered(lambda c: c.status == 'active')
                if active_contracts:
                    latest_active = active_contracts.sorted(
                        key=lambda r: (
                            r.start_date or date.min,
                            (r.create_date and r.create_date.date()) or date.min
                        ),
                        reverse=True
                    )[0]
                    record.contract_status = latest_active.status
                else:
                    contracts = record.contract_ids.sorted(
                        key=lambda r: (
                            r.start_date or date.min,
                            (r.create_date and r.create_date.date()) or date.min
                        ),
                        reverse=True
                    )
                    if contracts:
                        record.contract_status = contracts[0].status
                    else:
                        record.contract_status = 'pending'
            else:
                record.contract_status = False

    
    @api.depends('contract_ids.is_current')
    def _compute_current_contract(self):
        """Get the current active contract"""
        for record in self:
            if record.edu_type == 'academy':
                current_contract = record.contract_ids.filtered('is_current')
                record.current_contract_id = current_contract[0] if current_contract else False
            else:
                record.current_contract_id = False
    
    @api.depends('current_contract_id')
    def _compute_current_contract_data(self):
        """Get data from the current active contract"""
        for record in self:
            if record.edu_type == 'academy' and record.current_contract_id:
                record.revenue_share = record.current_contract_id.revenue_share
                record.responsible_employee_id = record.current_contract_id.responsible_employee_id
                record.contract_end_date = record.current_contract_id.end_date
            else:
                record.revenue_share = 0.0
                record.responsible_employee_id = False
                record.contract_end_date = False
    
    @api.depends('start_date', 'end_date')
    def _compute_status(self):
        today = date.today()
        for record in self:
            if record.end_date and record.end_date < today:
                record.status = 'expired'
            elif record.start_date and record.start_date > today:
                record.status = 'pending'
            else:
                if record.start_date and record.end_date and record.start_date <= record.end_date:
                    record.status = 'active'
                else:
                    record.status = 'pending'

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'name': _('Financial Settlements'),
            'type': 'ir.actions.act_window',
            'res_model': 'academy.financial.settlement',
            'view_mode': 'list,form',
            'domain': [('academy_id', '=', self.id),('is_center_settlement', '=', False)],
            'context': {'default_academy_id': self.id}
        }
    def _compute_settlement_count(self):
        for partner in self:
            if partner.edu_type == 'academy':
                partner.settlement_count = self.env['academy.financial.settlement'].with_context(skip_create_missing_settlements=True).search_count([
                    ('academy_id', '=', partner.id)
                ])
            else:
                partner.settlement_count = 0

    def cron_update_contract_status(self):
        """Cron job to automatically update contract status based on date"""
        today = date.today()
        academies = self.search([('edu_type', '=', 'academy')])
        for academy in academies:
            if academy.contract_start_date and academy.contract_end_date:
                if academy.contract_end_date < today:
                    academy.contract_status = 'expired'
                elif academy.contract_start_date > today:
                    academy.contract_status = 'pending'
                else:
                    academy.contract_status = 'active'
                      

    @api.depends('student_ids','offered_program_ids')
    def _compute_academy_students(self):
        for record in self:
            SaleOrder = self.env['sale.order']
            if record.edu_type == 'academy':
                domain = [
                    ('state', '=', 'sale'),
                    ('is_enrolment', '=', True),
                    ('order_line.academy_id', '=', record.id),
                ]
                sale_orders = SaleOrder.search(domain)
                record.student_ids = sale_orders.mapped('partner_id')
                record.academy_students_count = len(record.student_ids)
            else:
                record.student_ids = False 
                record.academy_students_count = 0


    def action_view_academy_students(self):
        """Open enrolled students (partners) under this academy"""
        self.ensure_one()

        # Base context
        ctx = {
            'default_edu_type': 'student',
            'list_view_ref': 'jucct.student_jucct_list_view',
            'form_view_ref': 'jucct.student_jucct_form_view',
            'default_invoice_template_pdf_report_id': self.env.ref('jucct.enrollment_invoice_report').id
        }

        # Add extra context if the current user is in a specific group
        if self.env.user.has_group('jucct.group_student_enrolment_rw'):
            ctx['create'] = True
        else:
            ctx['create'] = False

        action = self.env.ref('jucct.students_only_jucct_action').sudo().read()[0]
        action['domain'] = [('id', 'in', self.student_ids.ids)]
        action['views'] = [
            (self.env.ref('jucct.student_jucct_list_view').id, 'list'),
            (self.env.ref('jucct.student_jucct_form_view').id, 'form'),
        ]
        action['context'] = ctx
        return action
        
    def action_view_academy_invoices(self):
        """Smart button action to view invoices related to this academy"""
        self.ensure_one()
        action = self.env.ref('jucct.educational_customer_invoices_jucct_action').sudo().read()[0]
        action.update({
            'domain': [
                ('is_enrollment', '=', True),
                ('invoice_line_ids.academy_id', '=', self.id),
            ],
            'context': {
                'default_is_enrollment': True,
                'form_view_ref': 'jucct.account_move_form_juccty_view',
                'target': 'current',
            },
        })
        return action
    @api.depends()
    def _compute_academy_invoices_count(self):
        inv = self.env['account.move']
        domain = [
                ('is_enrollment', '=', True),
                ('invoice_line_ids.academy_id', '=', self.id),
                    ]
        self.academy_invoices_count = len(inv.search(domain))
    def action_view_academy_programs(self):
            self.ensure_one()
            
            action = self.env.ref('jucct.educational_courses_jucct_action').sudo().read()[0]
            
            action.update({
                'domain': [
                    ('offering_ids.academy_id', '=', self.id),
                    ('is_program', '=', True)
                ],
                'context': {'default_pro_read':True ,'default_program_type': 'course',
                'form_view_ref': 'jucct.educational_jucct_form_view'},
                'target': 'current',
                })

            return action

    @api.depends('offered_program_ids')
    def _compute_programs_count(self):
        for partner in self:
            partner.programs_count = len(partner.offered_program_ids)