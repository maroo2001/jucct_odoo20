from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class AcademySession(models.Model):
    _name = 'academy.session'
    _description = 'Academy Training Session'
    _order = 'is_pinned desc, academy_id, session_date asc, start_time asc' 
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Session Title', required=False)
    is_pinned = fields.Boolean(string="Always on Top", default=False) 
    record_type = fields.Selection([('not scheduled', 'Not Scheduled'), ('scheduled', 'Scheduled'), ('session day', 'Session Day')], string='Record Type', default='not scheduled')

    offering_id = fields.Many2one(
        'academy.program.offering',
        string='Offering',
        required=False
    )
    session_day_ids = fields.One2many(
        'session.day',
        'session_id',  
        string='Session Days'
    )

    available_academy_ids = fields.Many2many(
        'res.partner',
        compute='_compute_available_academies',
        store=False,
        string='Available Academies'
    )

    @api.depends('program_id')
    def _compute_available_academies(self):
        """Get academies that have offerings for the selected program"""
        for session in self:
            if session.program_id:

                offerings = self.env['academy.program.offering'].search([
                    ('program_id', '=', session.program_id.id)
                ])
                
                academy_ids = offerings.mapped('academy_id').ids
                
                if self.env.company.partner_id.id not in academy_ids:
                    academy_ids.append(self.env.company.partner_id.id)
                
                session.available_academy_ids = [(6, 0, academy_ids)]
            else:
                session.available_academy_ids = [(6, 0, [self.env.company.partner_id.id])]

    available_program_ids = fields.Many2many(
        'product.template',
        compute='_compute_available_programs',
        store=False,
        string='Available Programs'
    )

    @api.depends('academy_id')
    def _compute_available_programs(self):
        """Programs offered by the selected academy. No academy (or the center itself): all programs."""
        Offering = self.env['academy.program.offering']
        Program = self.env['product.template']
        center_id = self.env.company.partner_id.id
        for session in self:
            if session.academy_id and session.academy_id.id != center_id:
                programs = Offering.search([('academy_id', '=', session.academy_id.id)]).mapped('program_id')
            else:
                programs = Program.search([('is_program', '=', True)])
            session.available_program_ids = programs

    @api.onchange('academy_id')
    def _onchange_academy_clear_program(self):
        """If the new academy does not offer the selected program, clear program and offering."""
        for session in self:
            if session.academy_id and session.program_id and session.program_id not in session.available_program_ids:
                session.program_id = False
                session.offering_id = False



    center_partner_id = fields.Many2one(
        'res.partner',
        compute='_compute_center_partner',
        store=False
    )

    @api.depends_context('company')
    def _compute_center_partner(self):
        """Get current company's partner"""
        for session in self:
            session.center_partner_id = self.env.company.partner_id

    is_center_session = fields.Boolean(
        string='Is Center Session',
        compute='_compute_is_center_session',
        store=True
    )

    @api.depends('academy_id')
    def _compute_is_center_session(self):
        """Auto-compute based on academy"""
        for session in self:
            session.is_center_session = not bool(session.academy_id)

    program_type = fields.Selection([
        ('course', 'Course'),
        ('diploma', 'Diploma')
    ], string='Program Type', required=True, compute='_compute_from_offering', store=True, readonly=False)

    program_id = fields.Many2one(
        'product.template',
        string='Program',
        required=True,
        domain="[('is_program', '=', True), ('program_type', '!=', False), ('program_type', '=', program_type), ('id', 'in', available_program_ids)]",
        compute='_compute_from_offering',
        store=True,
        readonly=False
    )

    academy_id = fields.Many2one(
        'res.partner',
        string='Academy',
        domain="[('id', 'in', available_academy_ids)]",
        required=False,
        compute='_compute_from_offering',
        store=True,
        readonly=False,
        default=lambda self: self.env.company.partner_id.id
    )

    date_start = fields.Date(
        string='Offering Start',
        required=False,
        compute='_compute_from_offering',
        store=True,
        readonly=False 
    )

    date_end = fields.Date(
        string='Offering End',
        required=False,
        compute='_compute_from_offering',
        store=True,
        readonly=False  
    )

    session_date = fields.Date(
        string='Session Date',
        required=False
    )

    start_time = fields.Float(
        string='Start Time',
        compute='_compute_times_from_session_days',
        store=True,
        readonly=True,
        aggregator=False
    )

    end_time = fields.Float(
        string='End Time',
        compute='_compute_times_from_session_days',
        store=True,
        readonly=True,
        aggregator=False
    )
    @api.depends('session_day_ids', 'session_day_ids.start_time', 'session_day_ids.end_time', 'session_date')
    def _compute_times_from_session_days(self):
        """Get start/end time from matching session day based on session_date"""
        for session in self:
            if session.session_day_ids and session.session_date:
                # Get weekday from session_date (0=Monday, 6=Sunday)
                weekday = str(session.session_date.weekday())
                
                # Find matching day in session_day_ids
                matching_day = session.session_day_ids.filtered(lambda d: d.day_of_week == weekday)
                
                if matching_day:
                    # Use first matching day if multiple exist
                    session.start_time = matching_day[0].start_time
                    session.end_time = matching_day[0].end_time
                else:
                    # No matching day found, use first day as fallback
                    session.start_time = session.session_day_ids[0].start_time
                    session.end_time = session.session_day_ids[0].end_time
            elif session.session_day_ids:
                # No session_date but has session_days - use first one
                session.start_time = session.session_day_ids[0].start_time
                session.end_time = session.session_day_ids[0].end_time
            else:
                # No session days at all
                session.start_time = 0.0
                session.end_time = 0.0

    session_time_display = fields.Char(
        string='Session Time',
        compute='_compute_session_time_display',
        store=False
    )

    @api.depends('start_time', 'end_time')
    def _compute_session_time_display(self):
        """Display session time as 'HH:MM - HH:MM'"""
        for session in self:
            if session.start_time and session.end_time:
                start_hour = int(session.start_time)
                start_min = int((session.start_time - start_hour) * 60)
                end_hour = int(session.end_time)
                end_min = int((session.end_time - end_hour) * 60)
                session.session_time_display = "%02d:%02d - %02d:%02d" % (start_hour, start_min, end_hour, end_min)
            else:
                session.session_time_display = ""

    location = fields.Selection([
        ('inside', 'Inside University'),
        ('outside', 'Outside'),
        ('online', 'Online'),
    ], string='Actual Delivery Location', compute='_compute_from_offering', store=True, readonly=True)
    

    @api.depends('offering_id')
    def _compute_from_offering(self):
        """Auto-fill from offering when selected"""
        for session in self:
            if session.offering_id:
                session.program_type = session.offering_id.program_type
                session.program_id = session.offering_id.program_id
                session.academy_id = session.offering_id.academy_id

                if session.offering_id.start_date:
                    session.date_start = session.offering_id.start_date
                if session.offering_id.end_date:
                    session.date_end = session.offering_id.end_date

                if session.offering_id.program_id.venue:
                    session.location = session.offering_id.program_id.venue

                if session.offering_id.session_day_ids and not session.session_day_ids:
                    for day in session.offering_id.session_day_ids:
                        session.session_day_ids = [(0, 0, {
                            'day_of_week': day.day_of_week,
                            'trainer_id': day.trainer_id.id,
                            'start_time': day.start_time,
                            'end_time': day.end_time,
                        })]

    @api.constrains('date_start', 'date_end', 'offering_id')
    def _check_dates_match_offering(self):
        """Prevent manual modification of dates - must match offering"""
        for session in self:
            if session.offering_id:
                # Check if dates were manually changed
                if session.offering_id.start_date and session.date_start != session.offering_id.start_date:
                    raise ValidationError(
                        _("Cannot modify Start Date!\n\nStart date must match the offering date: %s\n\nIf you need to change it, please select a different offering.") 
                        % (session.offering_id.start_date.strftime('%d/%m/%Y') if session.offering_id.start_date else 'N/A')
                    )
                
                if session.offering_id.end_date and session.date_end != session.offering_id.end_date:
                    raise ValidationError(
                        _("Cannot modify End Date!\n\nEnd date must match the offering date: %s\n\nIf you need to change it, please select a different offering.") 
                        % (session.offering_id.end_date.strftime('%d/%m/%Y') if session.offering_id.end_date else 'N/A')
                    )
                
    offering_trainer_ids = fields.Many2many(
        'res.partner',
        compute='_compute_offering_trainers',
        store=False,
        string='Offering Trainers'
    )

    @api.depends('offering_id', 'offering_id.session_day_ids')
    def _compute_offering_trainers(self):
        """Get trainers from offering's session days"""
        for session in self:
            if session.offering_id and session.offering_id.session_day_ids:
                session.offering_trainer_ids = session.offering_id.session_day_ids.mapped('trainer_id')
            else:
                session.offering_trainer_ids = False

    trainer_id = fields.Many2one(
        'res.partner',
        string='Trainer',
        domain="[('is_trainer', '=', True), '|', ('id', 'in', offering_trainer_ids), ('id', 'in', academy_trainer_ids)]",
        required=False
    )

    academy_trainer_ids = fields.Many2many(
        'res.partner',
        compute='_compute_academy_trainers',
        store=False
    )

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

    available_offering_ids = fields.Many2many(
        'academy.program.offering',
        compute='_compute_available_offerings',
        store=False
    )

    @api.depends('academy_id', 'program_id')
    def _compute_available_offerings(self):
        """Get offerings based on selected academy and program"""
        for session in self:
            if session.academy_id and session.program_id:
                session.available_offering_ids = self.env['academy.program.offering'].search([
                    ('academy_id', '=', session.academy_id.id),
                    ('program_id', '=', session.program_id.id)
                ])
            elif session.program_id:
                session.available_offering_ids = self.env['academy.program.offering'].search([
                    ('program_id', '=', session.program_id.id),
                    ('academy_id', '=', self.env.company.partner_id.id)
                ])
            else:
                session.available_offering_ids = False

    status = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft')

    session_count = fields.Integer(
        string='Session Count',
        compute='_compute_session_count',
        store=False
    )

    is_current_user_trainer = fields.Boolean(
        string='Is Current User Trainer',
        compute='_compute_is_current_user_trainer',
        store=False
    )

    @api.depends('trainer_id')
    def _compute_is_current_user_trainer(self):
        """Check if current user is the trainer of this session"""
        current_user = self.env.user
        for session in self:
            session.is_current_user_trainer = (
                session.trainer_id and 
                current_user.partner_id and
                current_user.partner_id.id == session.trainer_id.id
            )

    @api.depends('program_id')
    def _compute_session_count(self):
        for session in self:
            session.session_count = 1

    def action_mark_done(self):
        """Mark session as done"""
        self.ensure_one()
        self.status = 'done'
        return True

    def action_schedule(self):
        """Schedule session"""
        self.ensure_one()
        self.status = 'scheduled'
        return True

    def action_cancel(self):
        """Cancel session"""
        self.ensure_one()
        self.status = 'cancelled'
        return True

    def action_generate_sessions(self):
        """Generate sessions from THIS session's session days (Smart - No Duplicates)"""
        self.ensure_one()
        
        if not self.session_day_ids:
            raise ValidationError(_("Please add session days first."))
        
        if not self.date_start or not self.date_end:
            raise ValidationError(_("Please select an offering first to set start/end dates."))
        
        from datetime import timedelta
        
        start_date = self.date_start
        end_date = self.date_end
        current_date = start_date
        
        created_count = 0
        skipped_count = 0
        
        existing_sessions = self.env['academy.session'].search([
            ('offering_id', '=', self.offering_id.id if self.offering_id else False),
            ('program_id', '=', self.program_id.id),
            ('academy_id', '=', self.academy_id.id),
            ('session_date', '>=', start_date),
            ('session_date', '<=', end_date),
        ])
        
        existing_dates_set = {
            (session.session_date, str(session.session_date.weekday()))
            for session in existing_sessions
        }
        
        # Unlink sessions that do not have corresponding session days
        for session in existing_sessions:
            weekday = str(session.session_date.weekday())
            matching_days = self.session_day_ids.filtered(lambda d: d.day_of_week == weekday)
            
            if not matching_days:
                session.unlink()
        
        while current_date <= end_date:
            weekday = str(current_date.weekday())
            
            # Find matching session days from THIS session
            matching_days = self.session_day_ids.filtered(lambda d: d.day_of_week == weekday)
            
            for session_day in matching_days:
                if (current_date, weekday) in existing_dates_set:
                    skipped_count += 1
                    continue
                
                new_session = self.env['academy.session'].with_context(jucct_skip_sync=True).create({
                    'name': _("%s - %s") % (self.program_id.name, current_date.strftime('%A %d %b')),
                    'record_type': 'session day',
                    'offering_id': self.offering_id.id if self.offering_id else False,
                    'program_type': self.program_type,
                    'program_id': self.program_id.id,
                    'academy_id': self.academy_id.id,
                    'trainer_id': session_day.trainer_id.id,
                    'session_date': current_date,
                    'location': self.location or 'inside',
                    'date_start' : self.offering_id.start_date if self.offering_id else False,
                    'date_end' : self.offering_id.end_date if self.offering_id else False,
                    'status': 'draft',
                    'session_day_ids': [(0, 0, {  
                        'day_of_week': session_day.day_of_week,
                        'trainer_id': session_day.trainer_id.id,
                        'start_time': session_day.start_time,
                        'end_time': session_day.end_time,
                    })],
                })
                created_count += 1
                existing_dates_set.add((current_date, weekday))
            
            current_date += timedelta(days=1)
        
        self.with_context(jucct_skip_sync=True).write({'record_type': 'scheduled'})
        if created_count == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Info'),
                    'message': _('No new sessions created. %s session(s) already exist.') % skipped_count,
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        message = _('%s new session(s) created!') % created_count
        if skipped_count > 0:
            message += _(' (%s existing session(s) skipped)') % skipped_count
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }

    @api.onchange('academy_id')
    def _onchange_academy_id(self):
        """Reset trainer and offering when academy changes"""
        if self.academy_id and self.academy_id.id != self.env.company.partner_id.id:
            if self.trainer_id and self.trainer_id.trainer_academy_id != self.academy_id:
                self.trainer_id = False
            self.offering_id = False
        else:
            if self.trainer_id and self.trainer_id.trainer_type != 'center':
                self.trainer_id = False
            self.offering_id = False

    @api.onchange('program_id')
    def _onchange_program_id(self):
        """Auto-fill location and reset offering, and check academy availability"""
        if self.program_id:
            if self.program_id.venue:
                self.location = self.program_id.venue
            if self.offering_id and self.offering_id.program_id != self.program_id:
                self.offering_id = False
            
            if self.academy_id and self.academy_id.id not in self.available_academy_ids.ids:
                self.academy_id = self.env.company.partner_id.id

    @api.onchange('offering_id')
    def _onchange_offering_id(self):
        """Auto-fill from offering when selected"""
        if self.offering_id:
            self.program_type = self.offering_id.program_type
            self.program_id = self.offering_id.program_id
            self.academy_id = self.offering_id.academy_id
            
            self.date_start = self.offering_id.start_date
            self.date_end = self.offering_id.end_date

            if self.offering_id.program_id.venue:
                self.location = self.offering_id.program_id.venue
            
            if self.offering_id.session_day_ids:
                for day in self.offering_id.session_day_ids:
                    self.session_day_ids = [(0, 0, {
                        'day_of_week': day.day_of_week,
                        'trainer_id': day.trainer_id.id,
                        'start_time': day.start_time,
                        'end_time': day.end_time,
                    })]
            
            # Reset trainer
            self.trainer_id = False


    @api.model_create_multi
    def create(self, vals_list):
        """Auto-fill location on create and sync session days to offering"""
        for vals in vals_list:
            existing_unscheduled = self.search([
                ('offering_id', '=', vals.get('offering_id')),
                ('record_type', '=', 'not scheduled'),
            ])
            if existing_unscheduled:
                existing_unscheduled.with_context(jucct_skip_sync=True).write({'record_type': 'scheduled'})


        for vals in vals_list:
            if vals.get('program_id') and not vals.get('location'):
                program = self.env['product.template'].browse(vals['program_id'])
                if program.venue:
                    vals['location'] = program.venue
        
        sessions = super().create(vals_list)
        
        for session in sessions:
            # sync session days into offering if needed
            if session.offering_id and session.session_day_ids:
                for day in session.session_day_ids:
                    existing = session.offering_id.session_day_ids.filtered(
                        lambda d: d.day_of_week == day.day_of_week and 
                                d.trainer_id == day.trainer_id and
                                d.start_time == day.start_time and
                                d.end_time == day.end_time
                    )
                    if not existing:
                        self.env['session.day'].create({
                            'offering_id': session.offering_id.id,
                            'day_of_week': day.day_of_week,
                            'trainer_id': day.trainer_id.id,
                            'start_time': day.start_time,
                            'end_time': day.end_time,
                        })
            # determine scheduled vs not scheduled using sync check (ensure actual instances exist)
            if self.env.context.get('jucct_skip_sync'):
                       return sessions
            try:
                synced = session._is_fully_synced_with_offering(check_instances=True)
            except Exception:
                synced = False

            if synced:
                if session.record_type != 'scheduled' and session.record_type != 'session day':
                    if session.name and session.name.endswith(_('edits - not scheduled')):
                        session.name = session.name.replace(_('edits - not scheduled'), '').strip() if session.name else _("%s - scheduled") % (session.program_id.name or _("Session"))

                    session.record_type = 'scheduled'
            else:
                if session.record_type == 'not scheduled' and (not session.name or not session.name.endswith(_('edits - not scheduled'))):
                    session.name = _("edits - not scheduled")
                    session.is_pinned = True
                if session.record_type == 'not scheduled':
                    continue
                if session.record_type != 'session day':
                    session.record_type = 'not scheduled'
                    session.is_pinned = True
               
        return sessions

    def write(self, vals):
        """Auto-fill location on write and sync session days to offering"""
        result = super().write(vals)
        
        for session in self:
            # Auto-fill location if program changed
            if 'program_id' in vals and session.program_id:
                if session.program_id.venue and 'location' not in vals:
                    session.location = session.program_id.venue
            
            # Sync new session days to offering
            if 'session_day_ids' in vals and session.offering_id:                
                # Update session days
                for day in session.session_day_ids:
                    existing = session.offering_id.session_day_ids.filtered(
                        lambda d: d.day_of_week == day.day_of_week and 
                                   d.trainer_id == day.trainer_id and
                                   d.start_time == day.start_time and
                                   d.end_time == day.end_time
                    )
                    if not existing:
                        # Add to offering
                        self.env['session.day'].create({
                            'offering_id': session.offering_id.id,
                            'day_of_week': day.day_of_week,
                            'trainer_id': day.trainer_id.id,
                            'start_time': day.start_time,
                            'end_time': day.end_time,
                        })
                session.offering_id.session_day_ids = session.session_day_ids

            # Recompute scheduled state using the stricter check
            if self.env.context.get('jucct_skip_sync'):
                return result
            try:
                synced = session._is_fully_synced_with_offering(check_instances=True)
            except Exception:
                synced = False

            if synced:
                if session.record_type != 'scheduled' and session.record_type != 'session day':
                    if session.name and session.name.endswith(_('edits - not scheduled')):
                        session.name = session.name.replace(_('edits - not scheduled'), '').strip() if session.name else _("%s - scheduled") % (session.program_id.name or _("Session"))
                    session.record_type = 'scheduled'
            else:
                if session.record_type == 'not scheduled' and (not session.name or not session.name.endswith(_('edits - not scheduled'))):
                    if session.name != _("edits - not scheduled"):
                       session.name = _("edits - not scheduled")
                       session.is_pinned = True
                if session.record_type == 'not scheduled':
                    continue
                if session.record_type != 'session day':
                    session.record_type = 'not scheduled'
                    session.is_pinned = True
        
        return result

    @api.constrains('session_date', 'date_start', 'date_end')
    def _check_session_date(self):
        """Validate session date is within offering period"""
        for session in self:
            if session.session_date and session.date_start and session.date_end:
                if session.session_date < session.date_start or session.session_date > session.date_end:
                    raise ValidationError(
                        _("Session date must be between %s and %s") % (session.date_start.strftime('%d/%m/%Y'), session.date_end.strftime('%d/%m/%Y'))
                    )

    @api.constrains('trainer_id', 'session_date', 'session_day_ids') 
    def _check_trainer_schedule_conflict(self):
        """Prevent scheduling conflicting sessions for the same trainer"""
        for session in self:
            if not session.trainer_id or not session.session_date or not session.session_day_ids:
                continue
            
            # Get time from session days
            if not session.session_day_ids:
                continue
                
            first_day = session.session_day_ids[0]
            session_start = first_day.start_time
            session_end = first_day.end_time
            
            # Search for other sessions of the same trainer on the same date
            conflicting_sessions = self.env['academy.session'].search([
                ('id', '!=', session.id),
                ('trainer_id', '=', session.trainer_id.id),
                ('session_date', '=', session.session_date),
                ('status', 'not in', ['cancelled']),
            ])
            
            # Check for time overlap
            for existing in conflicting_sessions:
                if not existing.session_day_ids:
                    continue
                
                existing_start = existing.session_day_ids[0].start_time
                existing_end = existing.session_day_ids[0].end_time
                
                if (session_start < existing_end and session_end > existing_start):
                    
                    def format_time(time_float):
                        hours = int(time_float)
                        minutes = int((time_float - hours) * 60)
                        return "%02d:%02d" % (hours, minutes)
                    
                    raise ValidationError(
                        _("Schedule Conflict!\n\nTrainer: %s\nDate: %s\n\nNew Session: %s - %s\nConflicts with existing session: %s - %s\nProgram: %s\n\nPlease select a different time slot.") % (
                            session.trainer_id.name,
                            session.session_date.strftime('%d/%m/%Y'),
                            format_time(session_start),
                            format_time(session_end),
                            format_time(existing_start),
                            format_time(existing_end),
                            existing.program_id.name
                        )
                    )
                        
    def action_mass_schedule(self):
        """Schedule multiple sessions at once"""
        draft_sessions = self.filtered(lambda s: s.status == 'draft')
        
        if not draft_sessions:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('No draft sessions selected to schedule.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        draft_sessions.write({'status': 'scheduled'})
        
        # ✅ Reload + Notification
        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': 'success',
            'title': _('Success'),
            'message': _('%s session(s) scheduled successfully!') % len(draft_sessions),
        })
        
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_mass_mark_done(self):
        """Mark multiple sessions as done at once"""
        scheduled_sessions = self.filtered(lambda s: s.status == 'scheduled')
        
        if not scheduled_sessions:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('No scheduled sessions selected to mark as done.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        scheduled_sessions.write({'status': 'done'})
        
        # ✅ Reload + Notification
        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': 'success',
            'title': _('Success'),
            'message': _('%s session(s) marked as done!') % len(scheduled_sessions),
        })
        
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_mass_cancel(self):
        """Cancel multiple sessions at once"""
        active_sessions = self.filtered(lambda s: s.status not in ['done', 'cancelled'])
        
        if not active_sessions:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('No sessions available to cancel.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        active_sessions.write({'status': 'cancelled'})
        
        # ✅ Reload + Notification
        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': 'success',
            'title': _('Success'),
            'message': _('%s session(s) cancelled!') % len(active_sessions),
        })
        
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _is_fully_synced_with_offering(self, check_instances=False):
        """Return True if session_day_ids match offering.session_day_ids.
        If check_instances=True also require at least one actual 'session day' record
        (academy.session with record_type='session day') to exist for each offering day
        within the offering start/end date that matches day_of_week/trainer/time.
        """
        self.ensure_one()
        if not self.offering_id:
            return False

        offering_days = self.offering_id.session_day_ids or self.env['session.day']
        # if session has no days, treat as not fully synced
        if not self.session_day_ids:
            return False

        # 1) Ensure every day on this session exists on the offering (same DOW/trainer/times)
        for day in self.session_day_ids:
            match = offering_days.filtered(lambda d: d.day_of_week == day.day_of_week and
                                                    (not d.trainer_id and not day.trainer_id or (d.trainer_id and day.trainer_id and d.trainer_id.id == day.trainer_id.id)) and
                                                    (d.start_time == day.start_time) and
                                                    (d.end_time == day.end_time))
            if not match:
                return False

        if not check_instances:
            return True

        # 2) For each offering day ensure at least one actual academy.session (record_type='session day')
        #    exists in the offering date range that matches dow/trainer/times.
        offer_start = self.offering_id.start_date
        offer_end = self.offering_id.end_date
        if not offer_start or not offer_end:
            return False

        for oday in offering_days:
            # build domain to find sessions in offering that match the weekday and trainer/time
            domain = [
                ('offering_id', '=', self.offering_id.id),
                ('record_type', '=', 'session day'),
                ('session_date', '>=', offer_start),
                ('session_date', '<=', offer_end),
            ]
            cand_sessions = self.env['academy.session'].search(domain, limit=50)
            found = False
            for s in cand_sessions:
                # compare weekday and first day times/trainer in the session instance
                if not s.session_date:
                    continue
                if str(s.session_date.weekday()) != str(oday.day_of_week):
                    continue
                # does the session instance have a matching session_day entry?
                sd_match = s.session_day_ids.filtered(lambda sd: sd.day_of_week == oday.day_of_week and
                                                         (not sd.trainer_id and not oday.trainer_id or (sd.trainer_id and oday.trainer_id and sd.trainer_id.id == oday.trainer_id.id)) and
                                                         sd.start_time == oday.start_time and
                                                         sd.end_time == oday.end_time)
                if sd_match:
                    found = True
                    break
            if not found:
                return False

        return True