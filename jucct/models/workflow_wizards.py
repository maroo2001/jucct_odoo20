from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import formatLang

class AcademyOfferWizard(models.TransientModel):
    _name = "academy.offer.wizard"
    _description = "Wizard: Create Academy Program Offering (multi-step with contract/approval)"

    # --- STATES ---
    state = fields.Selection([
        ('academy_basic', 'Academy — Basic'),
        ('academy_contract', 'Academy — Contract'),
        ('program_basic', 'Program — Basic'),
        ('program_approval', 'Program — Approval'),
        ('offering', 'Offering'),
        ('done', 'Done'),
    ], default='academy_basic', string="Step")

    # --- ACADEMY STEP ---
    academy_id = fields.Many2one('res.partner', string="Select Academy",         domain=lambda self: [
            '|',
            '&', ('edu_type', '=', 'academy'), ('contract_status', '=', 'active'),
            ('id', '=', self.env.company.partner_id.id)
        ],)
    create_new_academy = fields.Boolean("Create a new academy?", default=False)
    new_academy_name = fields.Char("Academy Name")
    country_id = fields.Many2one(
        'res.country',
        string="Country",
    )
    new_academy_phone = fields.Char("Phone")
    new_academy_email = fields.Char("Email")
    academy_notes = fields.Text(string="General Notes", help="General notes about the academy")
    academy_basic_tip = fields.Char(default=_("Tip: choose an existing academy or create a new one. Contract details come next if creating new."))
    academy_created_id = fields.Many2one('res.partner', string="Created Academy", readonly=True)

    # --- ACADEMY CONTRACT ---
    academy_contract_start = fields.Date("Contract Start Date")
    academy_contract_end = fields.Date("Contract End Date")
    attachment_ids = fields.Many2many('ir.attachment', string="Contract Files")
    academy_contract_filename = fields.Char(string="Contract Number")
    revenue_share = fields.Float(string="Commission Rate (%)", digits=(5, 2), required=True, tracking=True)
    academy_contract_notes = fields.Text("Notes about contract")
    responsible_employee_id = fields.Many2one('res.users', string="Responsible Employee", 
                                            default=lambda self: self.env.user.id, tracking=True)

    # --- PROGRAM STEP ---
    program_id = fields.Many2one('product.template', string="Select Program",
        domain=[('program_type','in', ['course','diploma']), ('status','=','active')])
    create_new_program = fields.Boolean("Create a new program?", default=False)

    new_program_name = fields.Char("Program Name")
    new_program_type = fields.Selection([('course','Course'), ('diploma','Diploma')], string="Program Type")
    new_program_venue = fields.Selection([('inside','Inside'), ('outside','Outside'), ('online','Online')], string="Venue")
    new_program_price = fields.Float("Default Price")
    new_program_comment = fields.Text(string="Internal Notes")
    program_basic_tip = fields.Char(default=_("Tip: choose a program or create a new one. Approval/official dates come next if creating new."))

    program_created_id = fields.Many2one('product.template', string="Created Program", readonly=True)

    # --- PROGRAM APPROVAL ---
    program_approval_start = fields.Date("Approval Start Date")
    program_approval_end = fields.Date("Approval End Date")
    approval_file = fields.Binary(string="Approval File")
    approval_number = fields.Char(string="Approval Number")

    # --- OFFERING STEP ---
    offering_start = fields.Date("Start Date")
    offering_end = fields.Date("End Date")
    offering_price = fields.Float("Custom Price", default=lambda self: self.program_id.list_price)
    offering_tip = fields.Char(default=_("Tip: Ensure dates fall within the program approval period (if applicable)."))

    offering_created_id = fields.Many2one('academy.program.offering', string="Created Offering", readonly=True)
    @api.onchange('program_id')
    def _onchange_program_id(self):
        """When program is selected in the wizard, use its list_price as default offering price."""
        if self.program_id:
            self.offering_price = self.program_id.list_price
    # --- UTILITY ---
    progress = fields.Float(string="Progress", compute="_compute_progress", store=False)
    summary_html = fields.Html(
        string="Summary",
        compute="_compute_summary_html",
        sanitize=False,
        readonly=True
    )

    printable_summary_html = fields.Html(
        string="Printable Summary",
        compute="_compute_printable_summary_html",
        sanitize=False,
        readonly=True
    )

    @api.depends('offering_created_id')
    def _compute_summary_html(self):
        for rec in self:
            if not rec.academy_id or not rec.program_id or not rec.offering_created_id:
                rec.summary_html = "<p class='text-muted'>Please complete previous steps first.</p>"
                continue

            # Get current contract and approval details
            academy = rec.offering_created_id.academy_id
            program = rec.offering_created_id.program_id
            offering = rec.offering_created_id
            
            # Get contract details
            contract = academy.current_contract_id
            contract_info = _("No active contract")
            if contract:
                contract_info = f"{contract.display_name} ({contract.start_date} to {contract.end_date})"
            
            # Get approval details  
            approval = program.approval_number
            approval_info = _("No active approval")
            if approval:
                approval_info = f"{program.approval_number} ({program.start_date} to {program.end_date})"
            
            # Calculate revenues
            center_revenue = ((100 - academy.revenue_share) * offering.price / 100) or 0
            academy_revenue = (academy.revenue_share * offering.price / 100) or 0

            rec.summary_html = f"""
            <div style="border:1px solid #ccc; border-radius:8px; padding:12px; {"direction:rtl;" if self.env.lang and self.env.lang.startswith('ar') else "direction:ltr;"} background-color:#f9f9f9;">
                <h3 style="color:#539273; margin-bottom:10px;">{_('Offering Summary')}</h3>
                <div style="display:flex; gap:40px;">
                    <div style="flex:1;">
                        <p><strong>{_('Academy')}:</strong> {academy.name}</p>
                        <p><strong>{_('Current Contract')}:</strong> {contract_info}</p>
                        <p><strong>{_('Program')}:</strong> {program.name}</p>
                    </div>
                    <div style="flex:1;">
                        <p><strong>{_('Current Approval')}:</strong> {approval_info}</p>
                        <p><strong>{_('Offering Start')}:</strong> {offering.start_date}</p>
                        <p><strong>{_('Offering End')}:</strong> {offering.end_date}</p>
                        <p><strong>{_('Offering Price')}:</strong> {formatLang(self.env, offering.price or 0, currency_obj=self.env.company.currency_id)}</p>
                    </div>
                </div>
                <div style="margin-top:15px; padding:10px; background-color:#f9f9f9; border-radius:5px;">
                    <h4 style="color:#539273; margin-bottom:8px;">{_('Revenue Share Analysis')}</h4>
                    <div style="display:flex; gap:40px;">
                        <div style="flex:1;">
                            <p><strong>{_('Center Expected Revenue')}:</strong> {formatLang(self.env, center_revenue, currency_obj=self.env.company.currency_id)} {_('per student')}</p>
                        </div>
                        <div style="flex:1;">
                            <p><strong>{_('Academy Expected Revenue')}:</strong> {formatLang(self.env, academy_revenue, currency_obj=self.env.company.currency_id)} {_('per student')}</p>
                        </div>
                    </div>
                    <p class="text-muted" style="margin-top:8px; font-size:0.9em;">
                        {_('Based on')} {academy.revenue_share}% {_('revenue share for academy')}
                    </p>
                </div>
                <hr/>
                <p><em>{_('Review these details. You can go back and make changes if needed.')}</em></p>
            </div>
            """


    @api.depends('state')
    def _compute_progress(self):
        mapping = {
            'academy_basic': 10,
            'academy_contract': 30,
            'program_basic': 50,
            'program_approval': 70,
            'offering': 90,
            'done': 100,
        }
        for rec in self:
            rec.progress = mapping.get(rec.state, 0)

    # ---------- NAVIGATION ----------
    def action_next(self):
        self.ensure_one()

        # --- ACADEMY BASIC ---
        if self.state == 'academy_basic':
            if self.create_new_academy:
                if not self.new_academy_name:
                    raise UserError(_("Please enter a name for the new academy before continuing."))
                self.state = 'academy_contract'
            else:
                if not self.academy_id:
                    raise UserError(_("Please select or create an academy to continue."))
                self.state = 'program_basic'

        # --- ACADEMY CONTRACT ---
        elif self.state == 'academy_contract':
            # Validate required fields
            if not self.academy_contract_start or not self.academy_contract_end:
                raise UserError(_("Please provide both contract start and end dates for the new academy."))
            if self.academy_contract_end < self.academy_contract_start:
                raise UserError(_("Contract end date cannot be before start date."))
            
            # Create or update academy
            academy_vals = {
                'name': self.new_academy_name,
                'phone': self.new_academy_phone,
                'email': self.new_academy_email,
                'edu_type': 'academy',
                'academy_notes': self.academy_notes
            }
            
            if self.academy_created_id:
                # Update existing academy
                self.academy_created_id.write(academy_vals)
                academy = self.academy_created_id
            else:
                # Create new academy
                academy = self.env['res.partner'].create(academy_vals)
                self.academy_created_id = academy.id
            
            # Set the academy_id reference
            self.academy_id = academy.id
            
            # Handle contract document
            if self.academy_id:
                self._check_revenue_share()
                # Create new attachment
                contract = self.env['academy.contract'].create({
                    'academy_id' : self.academy_id.id,
                    'contract_number': self.academy_contract_filename,
                    'start_date': self.academy_contract_start,
                    'end_date': self.academy_contract_end,
                    'revenue_share' : self.revenue_share,
                    'responsible_employee_id' : self.responsible_employee_id.id,
                    'notes' : self.academy_contract_notes,
                })
                self.attachment_ids.write({
                    'res_model': 'academy.contract',
                    'res_id': contract.id
                })
            
            self.state = 'program_basic'

        # --- PROGRAM BASIC ---
        elif self.state == 'program_basic':
                    if self.create_new_program:
                        if not self.new_program_name or not self.new_program_type:
                            raise UserError(_("Please provide a program name and type for the new program."))
                        
                        # MODIFICATION: Skip approval step for course programs
                        if self.new_program_type == 'course':
                            # Create program immediately without approval step
                            program_vals = {
                                'name': self.new_program_name,
                                'program_type': self.new_program_type,
                                'venue': self.new_program_venue,
                                'list_price': self.new_program_price,
                                'is_program': True,
                                'comment': self.new_program_comment 
                            }
                            
                            if self.program_created_id:
                                self.program_created_id.write(program_vals)
                                program = self.program_created_id
                            else:
                                program = self.env['product.template'].create(program_vals)
                                self.program_created_id = program.id
                            
                            self.program_id = program.id
                            self.program_id.cron_update_status()
                            self.offering_price = self.program_id.list_price
                            self.state = 'offering'
                        else:
                            # For diploma programs, go to approval step
                            self.state = 'program_approval'
                    else:
                        if not self.program_id:
                            raise UserError(_("Please select or create a program to continue."))
                        self.state = 'offering'

        # --- PROGRAM APPROVAL ---
        elif self.state == 'program_approval':
            # Only require approval validation for diploma programs
            if self.new_program_type == 'diploma':
                if not self.program_approval_start or not self.program_approval_end:
                    raise UserError(_("Please provide approval start and end dates for the new program."))
                if self.program_approval_end < self.program_approval_start:
                    raise UserError(_("Program approval end date cannot be before start date."))
                if not self.approval_number:
                    raise UserError(_("Please provide the official approval number for the new program."))
            
            # Create or update program
            program_vals = {
                'name': self.new_program_name,
                'program_type': self.new_program_type,
                'venue': self.new_program_venue,
                'list_price': self.new_program_price,
                'is_program': True,
                'comment': self.new_program_comment 
            }
            
            if self.program_created_id:
                self.program_created_id.write(program_vals)
                program = self.program_created_id
            else:
                program = self.env['product.template'].create(program_vals)
                self.program_created_id = program.id
            
            self.program_id = program.id
            
            # Only create approval record for diploma programs
            if self.new_program_type == 'diploma':
                self.env['educational.approval'].create({
                    'program_id': self.program_id.id,
                    'approval_number': self.approval_number,
                    'approval_file': self.approval_file,
                    'start_date': self.program_approval_start,
                    'end_date': self.program_approval_end
                })

            self.program_id.cron_update_status()
            self.offering_price = self.program_id.list_price
            self.state = 'offering'
        # --- OFFERING ---
        elif self.state == 'offering':
            # Validate required fields
            if not self.academy_id or not self.program_id:
                raise UserError(_("Please select/create an academy and program."))
            if not self.offering_start or not self.offering_end:
                raise UserError(_("Please provide offering start and end dates."))
            if self.offering_end < self.offering_start:
                raise UserError(_("Offering end date cannot be before start date."))

            # Create or update offering
            offering_vals = {
                'academy_id': self.academy_id.id,
                'program_id': self.program_id.id,
                'start_date': self.offering_start,
                'end_date': self.offering_end,
                'price': self.offering_price or 0.0,
            }
            self._check_offering_dates()
            if self.offering_created_id:
                # Update existing offering
                self.offering_created_id.write(offering_vals)
                offering = self.offering_created_id
            else:
                # Create new offering
                offering = self.env['academy.program.offering'].create(offering_vals)
                offering.cron_update_status()
                self.offering_created_id = offering.id
            
            self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'academy.offer.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    # --- GO BACK ---
    def action_back(self):
            self.ensure_one()
            
            # Define the navigation logic based on current state and user choices
            back_mapping = {
                'academy_contract': 'academy_basic',
                'program_basic': 'academy_basic' if not self.create_new_academy else 'academy_contract',
                'program_approval': 'program_basic',
                'offering': 'program_basic' if not self.create_new_program else (
                    'program_approval' if self.new_program_type == 'diploma' else 'program_basic'
                ),
                'done': 'offering',
            }
            
            if self.state in back_mapping:
                self.state = back_mapping[self.state]
            
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'academy.offer.wizard',
                'view_mode': 'form',
                'res_id': self.id,
                'target': 'new',
            }

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}

    # --- TOGGLES ---
    def toggle_create_new_academy(self):
        self.create_new_academy = not self.create_new_academy
        if self.create_new_academy:
            self.academy_id = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'academy.offer.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
    def action_existing_academy(self):
        """Reset academy creation state."""
        self.ensure_one()
        self.create_new_academy = False
        self.academy_id = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'academy.offer.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def toggle_create_new_program(self):
        self.create_new_program = not self.create_new_program
        if self.create_new_program:
            self.program_id = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'academy.offer.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
    
    def action_existing_program(self):
        """Reset program creation state."""
        self.ensure_one()
        self.create_new_program = False
        self.program_id = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'academy.offer.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
    
    def action_done(self):
        """Close wizard and open the offering form."""
        self.ensure_one()
        if not self.offering_created_id:
            raise UserError(_("No offering was created."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Offering'),
            'res_model': 'academy.program.offering',
            'view_mode': 'form',
            'res_id': self.offering_created_id.id,
            'target': 'current',
        }

    @api.constrains('revenue_share')
    def _check_revenue_share(self):
        for record in self:
            if record.revenue_share < 0 or record.revenue_share > 100:
                raise UserError(_("Revenue share must be between 0 and 100%"))
    
    @api.constrains('offering_start', 'offering_end')
    def _check_offering_dates(self):
        for rec in self:
            if not rec.offering_start or not rec.offering_end:
                continue

            # MODIFICATION: Only check program approval dates for diploma programs
            if rec.program_id and rec.program_id.program_type == 'diploma':
                if rec.program_id.start_date and rec.offering_start < rec.program_id.start_date:
                    raise UserError(_(
                        "Offering start date (%s) cannot be before program approval start date (%s)"
                    ) % (rec.offering_start, rec.program_id.start_date))

                if rec.program_id.end_date and rec.offering_end > rec.program_id.end_date:
                    raise UserError(_(
                        "Offering end date (%s) cannot be after program approval end date (%s)"
                    ) % (rec.offering_end, rec.program_id.end_date))

            contract = rec.academy_id.current_contract_id
            if contract:
                if contract.start_date and rec.offering_start < contract.start_date:
                    raise UserError(_(
                        "Offering start date (%s) cannot be before academy contract start date (%s)"
                    ) % (rec.offering_start, contract.start_date))

                if contract.end_date and rec.offering_end > contract.end_date:
                    raise UserError(_(
                        "Offering end date (%s) cannot be after academy contract end date (%s)"
                    ) % (rec.offering_end, contract.end_date))