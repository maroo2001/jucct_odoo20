from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class TrainerCertification(models.Model):
    _name = 'trainer.certification'
    _description = 'Trainer Certification'
    _order = 'issue_date desc'

    name = fields.Char(
        string='Certification Name',
        required=True,
        help='Name of the certification or qualification'
    )
    
    issuing_organization = fields.Char(
        string='Issuing Organization',
        help='Organization that issued the certification'
    )
    
    issue_date = fields.Date(
        string='Issue Date',
        help='Date when certification was obtained'
    )
    
    expiry_date = fields.Date(
        string='Expiry Date',
        help='Expiration date (if applicable)'
    )
    
    certification_number = fields.Char(
        string='Certificate Number',
        help='Certificate ID or reference number'
    )
    
    attachment = fields.Binary(
        string='Certificate File',
        help='Upload certificate document'
    )
    
    attachment_name = fields.Char(string='File Name')
    
    trainer_id = fields.Many2one(
        'res.partner',
        string='Trainer',
        required=True,
        ondelete='cascade',
        domain=[('is_trainer', '=', True)]
    )
    
    active = fields.Boolean(
        string='Active', 
        compute='_compute_active',
        store=True,
        readonly=False
    )
    
    is_expired = fields.Boolean(
        string='Expired',
        compute='_compute_active',
        store=True
    )
    
    @api.depends('expiry_date')
    def _compute_active(self):
        """Auto-update active status based on expiry date"""
        today = fields.Date.today()
        for cert in self:
            if cert.expiry_date:
                cert.is_expired = cert.expiry_date < today
                cert.active = not cert.is_expired
            else:
                cert.is_expired = False
                if not cert.active:
                    cert.active = True

    
    @api.constrains('issue_date', 'expiry_date')
    def _check_dates(self):
        for record in self:
            if record.issue_date and record.expiry_date:
                if record.expiry_date < record.issue_date:
                    raise ValidationError(_("Expiry date cannot be before the issue date."))