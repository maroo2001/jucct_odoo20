from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date 
import re
class Student(models.Model):
    _inherit = "res.partner"
    is_trainer = fields.Boolean(string="Is a Trainer", default=False)

    trainer_type = fields.Selection(
            selection=[('center', 'Center Trainer'), ('academy', 'Academy Trainer')],
            string="Trainer Type"
        )

    trainer_academy_id = fields.Many2one(
            'res.partner',
            string="Academy",
            domain=lambda self: [
            '|',
            '&', ('edu_type', '=', 'academy'), ('contract_status', '=', 'active'),
            ('id', '=', self.env.company.partner_id.id)
        ],
            help="If this trainer works for an academy, link the academy record here."
        )

    @api.onchange('is_trainer', 'trainer_type')
    def compute_center_trainer_display(self):
        for record in self:
            if record.is_trainer and record.trainer_type == 'center':
                record.trainer_academy_id = self.env.company.partner_id
                

    trainer_specialty = fields.Char(
        string="Specialty",
        help="Trainer's area of expertise or specialization"
    )
    
    trainer_ids = fields.One2many(
        'res.partner',
        'trainer_academy_id',
        string='Trainers',
        domain=[('is_trainer', '=', True), ('active', 'in', [True, False])]
    )

    trainer_count = fields.Integer(
        string='Trainer Count',
        compute='_compute_trainer_count',
        store=False
    )

    @api.depends('trainer_ids')
    def _compute_trainer_count(self):
        for academy in self:
            academy.trainer_count = len(academy.trainer_ids)


    def action_academy_trainers(self):
        """Open Academy Trainers in a popup filtered by this academy."""
        self.ensure_one()
        
        action = self.env.ref('jucct.trainer_jucct_action').sudo().read()[0]
        
        action.update({
            'domain': [
                ('is_trainer', '=', True),
                ('trainer_academy_id', '=', self.id),
            ],
            'context': dict(
                default_trainer_academy_id=self.id,
                default_is_trainer=True,
                default_trainer_type='academy',
                form_view_ref = 'jucct.trainer_jucct_form_view'
            ),
        })
        return action
 
               
    # Trainer-related fields and methods
    # Professional details

    years_experience = fields.Integer(
        string="Years of Experience",
        help="Total years of training/teaching experience",
        default=0
    )

    professional_notes = fields.Text(
        string="Professional Notes",
        help="Additional notes about trainer's expertise and background"
    )

    # -- Trainer <-> Sessions (One2many)
    trainer_session_ids = fields.One2many(
            'academy.session',
            'trainer_id',
            string='Trainer Sessions'
        )

    trainer_session_count = fields.Integer(
            string='Sessions Count',
            compute='_compute_trainer_session_count',
            store=False
        )
    

    @api.depends('trainer_session_ids')
    def _compute_trainer_session_count(self):
        """Count trainer's sessions using One2many relationship"""
        for partner in self:
            partner.trainer_session_count = len(partner.trainer_session_ids.filtered(lambda s: s.record_type == 'session day'))

    def action_trainer_sessions(self):
        """Open trainer's related sessions"""
        self.ensure_one()
        
        list_view_id = self.env.ref('jucct.academy_session_jucct_list_view').id
        editable_form_id = self.env.ref('jucct.academy_session_jucct_form_view').id
        readonly_form_id = self.env.ref('jucct.trainer_session_readonly_jucct_form_view').id
        
        return {
            'name': _('Trainer Sessions'),
            'type': 'ir.actions.act_window',
            'res_model': 'academy.session',
            'view_mode': 'list,form',
            'views': [
                (list_view_id, 'list'),
                (editable_form_id, 'form')  
            ],
            'domain': [('id', 'in', self.trainer_session_ids.ids),('record_type', '=', 'session day')],
            'context': {
                'default_trainer_id': self.id,
                'create': True,
                'edit': False,  
                'delete': False, 
                'group_by': ['program_id', 'offering_id'],
            },
            'target': 'current',
        }

    program_count = fields.Integer(
        string='Program Count',
        compute='_compute_program_count',
        store=False
    ) 

    @api.depends()
    def _compute_program_count(self):
        """Count programs where this trainer teaches (has sessions)"""
        for trainer in self:
            if trainer.is_trainer:
                # Count distinct programs from sessions
                sessions = self.env['academy.session'].search([
                    ('trainer_id', '=', trainer.id),('record_type', '=', 'session day')
                ])
                trainer.program_count = len(sessions.mapped('program_id'))
            else:
                trainer.program_count = 0


    def action_trainer_programs(self):
        """Open programs where trainer has sessions"""
        self.ensure_one()
        
        # Get program IDs from trainer's sessions
        sessions = self.env['academy.session'].search([
            ('trainer_id', '=', self.id),('record_type', '=', 'session day')
        ])
        program_ids = sessions.mapped('program_id').ids
        
        # Get the custom views
        list_view_id = self.env.ref('jucct.educational_jucct_list_view').id
        form_view_id = self.env.ref('jucct.educational_jucct_form_view').id
        
        return {
            'name': _('Trainer Programs'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'views': [(list_view_id, 'list'), (form_view_id, 'form')],
            'domain': [('id', 'in', program_ids)],
            'context': {
                'create': False,  # منع الإنشاء
                'edit': False,    # منع التعديل
            },
            'target': 'current',
        }
    
    @api.constrains('years_experience')
    def _check_years_experience(self):
        """Validate years of experience"""
        for record in self:
            if record.years_experience and record.years_experience < 0:
                raise ValidationError(_("Years of Experience cannot be negative."))
            

    # Trainer Certifications 
    certification_ids = fields.One2many(
        'trainer.certification',
        'trainer_id',
        string='Certifications'
    )

    certification_count = fields.Integer(
        string='Certification Count',
        compute='_compute_certification_count',
        store=False
    )

    @api.depends('certification_ids')
    def _compute_certification_count(self):
        """Count trainer certifications"""
        for trainer in self:
            trainer.certification_count = len(trainer.certification_ids)

    def action_trainer_certifications(self):
        """Open trainer certifications"""
        self.ensure_one()
        
        return {
            'name': _('Certifications'),
            'type': 'ir.actions.act_window',
            'res_model': 'trainer.certification',
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [('trainer_id', '=', self.id)],
            'context': {
                'default_trainer_id': self.id,
            }
        }
