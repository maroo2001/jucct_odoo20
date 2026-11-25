from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta, datetime
from odoo.fields import Datetime as OdooDatetime
import pytz


class AcademyProgramOffering(models.Model):
    _name = 'academy.program.offering'
    _description = 'Academy Program Offering'
    _rec_name = 'display_name'  
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # NEW: Sequence Number Field
    sequence_number = fields.Char(
        string="Offering Reference",
        readonly=True,
        copy=False,
        help="Auto-generated unique reference number for the offering"
    )

    academy_id = fields.Many2one(
        'res.partner',
        string="Academy",
        required=True,
        context={'action_id': 'jucct.academies_only_jucct_action','form_view_ref': 'jucct.academy_jucct_form_view'},
        domain=lambda self: [
            '|',
            '&', ('edu_type', '=', 'academy'), ('contract_status', '=', 'active'),
            ('id', '=', self.env.company.partner_id.id)
        ],
    )
    
    program_id = fields.Many2one(
        'product.template',
        string="Program",
        required=True,
        domain=[('program_type', 'in', ['course', 'diploma']), ('status', '=', 'active')],
    )

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True
    )
    settlement_ids = fields.One2many(
        'academy.financial.settlement', 'offering_id', string="settlement")

    @api.depends('program_id', 'start_date', 'end_date')
    def _compute_display_name(self):
        """Display the program name with the start and end date."""
        for record in self:
            if record.program_id and record.start_date and record.end_date:
                record.display_name = f" {record.program_id.name} ({record.start_date.strftime('%d/%m/%Y')} - {record.end_date.strftime('%d/%m/%Y')}) "
            elif record.program_id:
                record.display_name = record.program_id.name
            else:
                record.display_name = "New Offering"

    price = fields.Float(string="Custom Price",)
    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string=_("End Date"), required=True)
    status = fields.Selection([
        ('draft', _('Draft')),
        ('pending', _('Pending')),
        ('active', _('Active')),
        ('expired', _('Expired')),
    ], string=_("Status"), store=True)

    program_type = fields.Selection(related='program_id.program_type', store=True)
    approval_start = fields.Date(related='program_id.start_date', store=True)
    approval_end = fields.Date(related='program_id.end_date', store=True)
    enrolled_students = fields.Many2one(
        'res.partner', string="Enrolled Students", compute='compute_enrolled_students', store=True)
    session_generated = fields.Boolean(string="Sessions Generated", default=False)

    # Smart button fields
    academy_name = fields.Char(related='academy_id.name', string="Academy Name", readonly=True)
    program_name = fields.Char(related='program_id.name', string="Program Name", readonly=True)
    session_ids = fields.One2many(
        'academy.session', 'offering_id', string="Sessions")
    session_day_ids = fields.One2many(
        'session.day',
        'offering_id',
        string="Session Days"
    )
    academy_trainer_ids = fields.Many2many(
        'res.partner',
        compute='_compute_academy_trainers',
        store=False
    )

    def action_generate_sequence_number(self):
            """Generate sequence number for records without one."""
            for record in self:
                if not record.sequence_number:
                    record.sequence_number = self.env['ir.sequence'].next_by_code('academy.program.offering.sequence') or _('New')

    @api.depends('status', 'academy_id', 'start_date', 'end_date') 
    def _create_center_settlement(self):
        """Compute the center settlement for each offering."""
        for record in self:
            # Check for existing settlement
            existing = self.env['academy.financial.settlement'].search([
                ('offering_id', '=', record.id)
            ], limit=1)
            
            if existing:
                record.settlement_ids = [(4, existing.id)]
                continue

            # Only proceed for center offerings that are expired
            if record.academy_id.id != self.env.company.partner_id.id or record.status != 'expired':
                continue

            # Create settlement record
            settlement = self.env['academy.financial.settlement'].create({
                'academy_id': record.academy_id.id,
                'program_id': record.program_id.id,
                'offering_id': record.id,
                'is_center_settlement': True,
                'settlement_status': 'paid',
            })
            settlement.offering_id = record # Ensure offering_id is set
            settlement.is_center_settlement = True
            record.settlement_ids = [(4, settlement.id)]
    
    def create_sessions(self):
        """Generate sessions from offering (called from button)"""
        new_session = self.env['academy.session'].create({
            'record_type': 'not scheduled',
            'offering_id': self.id if self.id else False,
            'program_type': self.program_id.program_type,
            'program_id': self.program_id.id,
            'academy_id': self.academy_id.id,
            'date_end' : self.end_date,
            'date_start' : self.start_date,
            'location': self.program_id.venue or 'inside',
            'status': 'draft',
            'session_day_ids': self.session_day_ids.ids,
        })
        new_session.action_generate_sessions()

    def _generate_sessions(self):
        """Create academy.session records based on session.day config (Smart - No Duplicates)"""
        session_model = self.env['academy.session']

        for offering in self:
            if not offering.start_date or not offering.end_date:
                continue
            if not offering.session_day_ids:
                continue

            existing_sessions = session_model.search([
                ('offering_id', '=', offering.id),
                ('record_type', '=', 'session day')
            ])
            
            existing_dates_set = {
                (session.session_date, str(session.session_date.weekday()))
                for session in existing_sessions
            }

            start_date = offering.start_date
            end_date = offering.end_date
            current_date = start_date
            
            created_count = 0
            skipped_count = 0

            while current_date <= end_date:
                weekday = str(current_date.weekday())  # 0 = Monday ... 6 = Sunday
                
                # Find all configured session days matching this weekday
                for config in offering.session_day_ids.filtered(lambda d: d.day_of_week == weekday):
                    if (current_date, weekday) in existing_dates_set:
                        skipped_count += 1
                        continue
                    
                    session_model.create({
                        'name': f"{offering.program_id.name} - {current_date.strftime('%A %d %b')}",
                        'offering_id': offering.id,
                        'record_type': 'session day',
                        'program_type': offering.program_type,
                        'program_id': offering.program_id.id,
                        'academy_id': offering.academy_id.id,
                        'trainer_id': config.trainer_id.id,
                        'session_date': current_date,
                        'start_time': config.start_time,  
                        'end_time': config.end_time,
                        'date_start' : offering.start_date,
                        'date_end' : offering.end_date,      
                        'location': offering.program_id.venue or 'inside',
                        'status': 'draft',
                    })
                    created_count += 1
                    
                    existing_dates_set.add((current_date, weekday))
                
                current_date += timedelta(days=1)
            
            if created_count > 0:
                offering.session_generated = True
        
    @api.depends('academy_id', 'program_id')
    def compute_enrolled_students(self):
        for record in self:
            if record.academy_id and record.program_id:
                domain = [
                    ('state', '=', 'sale'),
                    ('is_enrolment', '=', True),
                    ('order_line.academy_id', '=', record.academy_id.id),
                    ('order_line.product_id', '=', record.program_id.id),
                    ('order_line.class_offering_id', '=', record.id)
                ]
                sale_orders = self.env['sale.order'].search(domain)
                record.enrolled_students = sale_orders.mapped('partner_id')
            else:
                record.enrolled_students = 0

    # Validation rule
    @api.constrains('start_date', 'end_date', 'program_id', 'academy_id')
    def _check_dates_within_approval_period(self):
        for rec in self:
            if not rec.program_id:
                continue

            # Check if program is active
            if rec.program_id.status != 'active' and rec.program_id.program_type != 'course':
                raise ValidationError(
                    _("The program offered '%s' isn't active. Please review its approval document.") % (rec.program_id.display_name,)
                )

            # Check program approval dates
            if rec.program_id.start_date and rec.program_id.end_date:
                if rec.start_date < rec.program_id.start_date or rec.end_date > rec.program_id.end_date:
                    raise ValidationError(_(
                        "The course offering period of '%s' must be within its official approval period. "
                        "The approval period is from %s to %s. Please adjust the dates accordingly."
                    ) % (
                        rec.program_id.display_name,
                        rec.program_id.start_date,
                        rec.program_id.end_date
                    ))

            # Check academy contract dates (only for external academies, not center)
            if rec.academy_id and rec.academy_id.edu_type == 'academy':
                contract = rec.academy_id.current_contract_id
                if not contract:
                    raise ValidationError(_(
                        "Academy '%s' has no active contract. Please create a contract before creating offerings."
                    ) % (rec.academy_id.name,))

                if contract.start_date and rec.start_date < contract.start_date:
                    raise ValidationError(_(
                        "Offering start date (%s) cannot be before academy contract start date (%s). "
                        "Academy: %s, Contract: %s"
                    ) % (rec.start_date, contract.start_date, rec.academy_id.name, contract.display_name))

                if contract.end_date and rec.end_date > contract.end_date:
                    raise ValidationError(_(
                        "Offering end date (%s) cannot be after academy contract end date (%s). "
                        "Academy: %s, Contract: %s"
                    ) % (rec.end_date, contract.end_date, rec.academy_id.name, contract.display_name))

            # Check basic date logic
            if rec.end_date < rec.start_date:
                raise ValidationError(_("End date cannot be before start date."))

    @api.onchange('start_date', 'end_date')
    def _compute_status(self):
        today = fields.Date.today()
        for rec in self:
            if not rec.start_date or not rec.end_date:
                rec.status = 'draft'
                continue

            if rec.end_date < today:
                rec.status = 'expired'
            elif rec.start_date > today:
                rec.status = 'pending'
            elif rec.start_date <= today <= rec.end_date:
                rec.status = 'active'
            else:
                rec.status = 'draft'
            rec._update_pending_suffix()

    @api.model_create_multi
    def create(self, vals_list):
        # Generate sequence number for offerings
        for vals in vals_list:
            if not vals.get('sequence_number'):
                vals['sequence_number'] = self.env['ir.sequence'].next_by_code('academy.program.offering.sequence') or _('New')
        return super().create(vals_list)

    def cron_update_status(self):
        """Daily job to update offering status based on start/end dates."""
        today = fields.Date.today()
        offerings = self.search([])
        for rec in offerings:
            if not rec.start_date or not rec.end_date:
                new_status = 'draft'
            elif rec.end_date < today:
                new_status = 'expired'
            elif rec.start_date > today:
                new_status = 'pending'
            elif rec.start_date <= today <= rec.end_date:
                new_status = 'active'
            else:
                new_status = 'draft'

            if rec.status != new_status:
                rec.status = new_status
            rec._update_pending_suffix()
            rec._create_center_settlement()

    def _update_pending_suffix(self):
        """Append or remove '(Pending)' from display name based on status."""
        for rec in self:
            if not rec.display_name:
                continue

            name = rec.display_name.strip()
            pending_suffix = " (Pending)"

            if rec.status == 'pending':
                if not name.endswith(pending_suffix):
                    rec.display_name = f"{name}_{pending_suffix}"
            else:
                if name.endswith(pending_suffix):
                    rec.display_name = name.replace(pending_suffix, "").strip()

    @api.depends('academy_id')
    def _compute_academy_trainers(self):
        """Get trainers: center trainers OR academy trainers"""
        for session in self:
            if session.academy_id and session.academy_id.id != self.env.company.partner_id.id:
                session.academy_trainer_ids = self.env['res.partner'].search([
                    ('is_trainer', '=', True),
                    ('trainer_academy_id', '=', session.academy_id.id)
                ])
            else:
                session.academy_trainer_ids = self.env['res.partner'].search([
                    ('is_trainer', '=', True),
                    ('trainer_type', '=', 'center')
                ])

    @api.onchange('program_id')
    def _compute_program_price(self):
        for rec in self:
            rec.price = rec.program_id.list_price if rec.program_id else 0.0

    @api.constrains('price', 'start_date', 'end_date')
    def _check_price_and_dates(self):
        for rec in self:
            if rec.price < 0:
                raise ValidationError(_("Price cannot be negative."))
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("End date cannot be before start date."))        


class SessionDay(models.Model):
    _name = 'session.day'
    _description = 'Session Day'

    offering_id = fields.Many2one('academy.program.offering', string="Offering", ondelete='cascade')
    session_id = fields.Many2one('academy.session', string="Session", ondelete='cascade')
    
    day_of_week = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    ], string="Day of Week", required=True)
    
    academy_trainer_ids = fields.Many2many(
        'res.partner',
        related='offering_id.academy_trainer_ids',
        string='Available Trainers',
        domain="[|,('trainer_academy_id', '=', offering_id.academy_id),('trainer_type', '=', 'center')]"
    )
    
    trainer_id = fields.Many2one('res.partner', string="Trainer", domain=[('is_trainer', '=', True)], required=True)
    start_time = fields.Float(string="Start Time (hours)", required=True)  
    end_time = fields.Float(string="End Time (hours)", required=True)

    @api.constrains('start_time', 'end_time')
    def _check_times(self):
        for rec in self:
            if rec.start_time < 0 or rec.end_time < 0:
                raise ValidationError(_("Start and End times cannot be negative."))
            if rec.end_time <= rec.start_time:
                raise ValidationError(_("End time must be greater than Start time."))