from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import ValidationError
from datetime import date

SALE_ORDER_STATE = [
    ('draft', "Quotation"),
    ('sent', "Quotation Sent"),
    ('sale', "Sales Order"),
    ('cancel', "Cancelled"),
]
ENROLMENT_STATE = [
    ('draft', "Draft"),
    ('sent', "Draft"),
    ('sale', "confirmed"),
    ('cancel', "withdrawn"),
]


class SalesOrder(models.Model):
    _inherit = 'sale.order'

    state = fields.Selection(
        selection=lambda self: self._get_enrolment_statuses(),
        string="Status",
        readonly=True, copy=False, index=True,
        tracking=3,
        default='draft')

    year = fields.Char(string='Year')
    semester = fields.Selection([
        ('first', 'First Semester'),
        ('second', 'Second Semester'),
        ('summer', 'Summer Semester')
    ], string='Semester')

    program_price = fields.Float(
        string='Program Price', 
        compute='_compute_program_price',
        store=True,
        readonly=True, 
        aggregator='avg'
    )
    @api.depends('order_line.price_subtotal')
    def _compute_program_price(self):
        for order in self:
            if order.is_enrolment and order.order_line:
                order.program_price = order.order_line[0].price_subtotal if order.order_line else 0.0
            else:
                order.program_price = 0.0
                
    is_enrolment = fields.Boolean(string='Is an Enrolment Record')
    program_type = fields.Selection([
        ('course','Course'),
        ('diploma','Diploma')
    ], string="Program Type", default='course')
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Customer" if not is_enrolment else "Student" ,
        required=True, change_default=True, index=True,
        tracking=1,
        check_company=True)
    user_id = fields.Many2one(
        comodel_name='res.users',
        string="Salesperson" if not is_enrolment else "Registerer",
        compute='_compute_user_id',
        store=True, readonly=False, precompute=True, index=True,
        tracking=2,
        domain=lambda self: "[('all_group_ids', 'in', [{}]), ('share', '=', False), ('company_ids', '=', company_id)]".format(
            self.env.ref("sales_team.group_sale_salesman").id
        ))
    amount_untaxed = fields.Monetary(string="Untaxed Amount", store=True, compute='_compute_amounts', tracking=5 if not is_enrolment else None)


    def _creation_message(self):
        """Customize the creation message for Sale Orders that are enrolments.
        For other models, fall back to the default mail.thread behavior.
        """
        self.ensure_one()

        if self._name == 'sale.order' and getattr(self, 'is_enrolment', False):
            doc_name = _("Enrolment Record")
            return _('%s created') % doc_name

        return super()._creation_message()
    
    def _get_enrolment_statuses(self):
        if self.env.context.get('enrolment_mode'):
            return ENROLMENT_STATE
        else:
            return SALE_ORDER_STATE
    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values and self.state == 'sale' and self.is_enrolment:
            return self.env.ref('jucct.mt_enrolment_confirmed')
        if 'state' in init_values and self.state == 'sent' and self.is_enrolment:
            return self.env.ref('jucct.mt_enrolment_confirmed')
        if 'state' in init_values and self.state == 'mt_enrolment_created':
            return self.env.ref('sale.mt_order_confirmed')
        elif 'state' in init_values and self.state == 'sent':
            return self.env.ref('sale.mt_order_sent')
        if getattr(self, 'is_enrolment', False):
            init_values = {k: v for k, v in init_values.items() if k != 'amount_untaxed'}
        return super()._track_subtype(init_values)

        
    university_id = fields.Char(string="Student ID", readonly=True, copy=False)
    
    enrolment_status = fields.Selection([
        ('draft','Draft'),
        ('confirmed','Confirmed'),
        ('withdrawn','Withdrawn')  
    ], string="State", compute='_compute_enrolment_status', store=True)
    
    payment_term_id = fields.Many2one(
        'account.payment.term',
        compute='_compute_payment_term_id_en',
    )
    withdrawal_fine = fields.Float(string="Withdrawal Fine", help="Fine amount for student withdrawal")
    apply_fine = fields.Boolean(string="Apply Fine", default=False)

    def action_withdraw_student(self):
        """تنفيذ عملية انقطاع الطالب مع إمكانية تطبيق غرامة"""
        self.ensure_one()
        
        if self.enrolment_status != 'confirmed':
            raise ValidationError(_("Can only withdraw confirmed enrollments."))
        
        popup = self.env['withdrawal.fine.wizard'].sudo().create({
            'order_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Set Withdrawal Fine'),
            'res_model': 'withdrawal.fine.wizard',
            'view_mode': 'form',
            'res_id': popup.id,
            'target': 'new',
        }

    def _update_existing_invoice_for_withdrawal(self):
        """تحديث الفاتورة الموجودة عند الانقطاع"""
        self.ensure_one()

        existing_invoice = self.invoice_ids.filtered(
            lambda i: i.state in ('draft', 'posted') and 
            i.move_type == 'out_invoice' and 
            not i.reversed_entry_id
        )


        if not existing_invoice:
            raise ValidationError(_("No invoice found for this order to update."))
        

        invoice = existing_invoice[0]
        wizard = self.env['account.payment.register'].with_context(
                    active_model='account.move',
                    active_ids=invoice.ids,
                ).create({
                    'amount': self.withdrawal_fine,
                    'payment_date': fields.Date.context_today(self),
                    'journal_id': self.env['account.journal'].search([('type', '=', 'cash')], limit=1).id,
                })
        wizard.action_create_payments()
        invoice.is_withdraw = True
        invoice.withdrawal_fine = self.withdrawal_fine
        return invoice
    

    def action_rset_to_draft(self):
            for order in self:
                if order.is_enrolment and order.enrolment_status == 'withdrawn':
                    order.invoice_ids.is_withdraw = 0
                order.enrolment_status = 'draft'
                order._action_cancel()
                order.write({'state': 'draft'})
    @api.depends('state')
    def _compute_enrolment_status(self):
        for order in self:
            if order.enrolment_status != 'withdrawn':
                order.enrolment_status = 'confirmed' if order.state == 'sale' else 'draft'

    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        if self.is_enrolment:
            values['is_enrollment'] = True
        if self.program_type == 'diploma':
            values['program_type'] = 'diploma'     
            values['university_id'] = self.university_id if self.university_id else None
            values['created_by'] = self.env.user.id
        return values

    @api.depends('partner_id')
    def _compute_payment_term_id_en(self):
        for order in self:
            order.partner_id.invoice_template_pdf_report_id = order.env.ref('jucct.enrollment_invoice_report', raise_if_not_found=False)
            if not order.is_enrolment:
                super(SalesOrder, order)._compute_payment_term_id()

    def create_regular_invoice_directly_action(self):
        # ensure the orders exist in DB

        Wizard = self.env['sale.advance.payment.inv'].sudo()
        wizard = Wizard.sudo().create({
            'advance_payment_method': 'delivered',
            'sale_order_ids': [(6, 0, self.ids)],
        })

        # Call the wizard properly by passing its sale_order_ids (matches provided wizard implementation)
        invoices = wizard.sudo()._create_invoices(wizard.sale_order_ids)

        # cleanup transient wizard
        try:
            wizard.unlink()
        except Exception:
            pass

        return self.action_view_invoice(invoices=invoices)
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        preserved = {o.id: o.payment_term_id.id for o in self if o.is_enrolment}
        parent_onchange = getattr(super(SalesOrder, self), '_onchange_partner_id', None)
        if parent_onchange:
            parent_onchange()
        for order in self:
            if order.is_enrolment:
                term_id = preserved.get(order.id)
                order.payment_term_id = self.env['account.payment.term'].browse(term_id) if term_id else False
    def _check_enrolment_conflicts(self):
        """Check all enrolment lines for time conflicts."""
        self.ensure_one()
        conflict_messages = []

        enrolment_lines = self.order_line.filtered(lambda l: l.is_enrolment and l.class_offering_id)
        if not enrolment_lines:
            return False, None

        for line in enrolment_lines:
            conflicts = line._get_conflicting_sessions()
            if conflicts:
                msg = "\n".join([
                    _("• %s (%s %s–%s)") % (
                        c['date'], c['other_name'], c['start'], c['end']
                    ) for c in conflicts
                ])
                conflict_messages.append(
                    _("Conflicts for offering '%s':\n%s") % (line.class_offering_id.display_name, msg)
                )

        if conflict_messages:
            return True, "\n\n".join(conflict_messages)
        return False, None

    def action_confirm(self):
        for order in self:
            if not all(line.class_offering_id for line in order.order_line) and order.is_enrolment or not order.order_line and order.is_enrolment:
                raise ValidationError(_("Class offering is required for all order lines."))
            if order.is_enrolment and not self.env.context.get('bypass_conflict_check'):
                has_conflicts, message = order._check_enrolment_conflicts()
                if has_conflicts:
                    return {
                        'type': 'ir.actions.act_window',
                        'res_model': 'enrolment.conflict.wizard',
                        'view_mode': 'form',
                        'target': 'new',
                        'context': {
                            'default_message': _("The following conflicts were detected:\n\n%s") % message,
                            'default_order_id': order.id,
                        }
                    }
        for order in self:
            res = super(SalesOrder, order).action_confirm()
            if order.is_enrolment:
                order.university_id = order.partner_id.university_id
                if order.program_type == 'diploma' and order.partner_id.university_id == "N/A":
                    if order.order_line:
                        line = order.order_line[0]
                        year = line.year
                        semester = line.semester
                        
                        # التحقق من وجود السنة والفصل الدراسي
                        if not year:
                            raise ValidationError(_("Year is required to generate the Student ID."))
                        if not semester:
                            raise ValidationError(_("Semester is required to generate the Student ID."))
                        
                        # استخراج بادئة الرقم الجامعي (السنة والفصل)
                        year_short = str(year)[-2:]
                        semester_digit = str(1 if semester == 'first' else 2 if semester == 'second' else 3)
                        prefix = f"{year_short}{semester_digit}"
                        
                        # التعديل هنا: البحث عن أعلى رقم جامعي موجود يبدأ بهذه البادئة
                        last_student = self.env['res.partner'].search([
                            ('university_id', '=like', f'{prefix}%')
                        ], order='university_id desc', limit=1)
                        
                        if last_student and last_student.university_id:
                            # استخراج آخر 3 أرقام وزيادتها بواحد
                            last_seq_str = last_student.university_id[len(prefix):]
                            try:
                                next_seq = int(last_seq_str) + 1
                            except ValueError:
                                next_seq = 1
                        else:
                            # إذا لم يكن هناك أي طالب في هذا الفصل، نبدأ من 1
                            next_seq = 1
                            
                        sequence_num = str(next_seq).zfill(3)
                        university_id = f"{prefix}{sequence_num}"
                        
                        # التحقق الاحتياطي من عدم تكرار الرقم الجامعي
                        while self.env['res.partner'].search_count([('university_id', '=', university_id)]):
                            next_seq += 1
                            sequence_num = str(next_seq).zfill(3)
                            university_id = f"{prefix}{sequence_num}"
                            
                        order.partner_id.university_id = university_id
                        order.university_id = university_id
                        
                # إظهار نافذة التأكيد
                popup = self.env['sale.order.popup.wizard'].sudo().create({
                    'order_id': order.id,
                    'university_id': order.university_id,
                    'program_type': order.program_type,
                    'year': order.order_line[0].year if order.order_line else '',
                    'semester': order.order_line[0].semester if order.order_line else '',
                })
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Enrollment Confirmation'),
                    'res_model': 'sale.order.popup.wizard',
                    'view_mode': 'form',
                    'res_id': popup.id,
                    'target': 'new',  
                }
        return res

    

class WithdrawalFineWizard(models.TransientModel):
    _name = 'withdrawal.fine.wizard'
    _description = 'Wizard to set withdrawal fine'
    
    order_id = fields.Many2one('sale.order', string="Order", required=True)
    apply_fine = fields.Boolean(string="Apply Fine", default=False)
    withdrawal_fine = fields.Float(string="Withdrawal Fine Amount")
    
    def action_confirm_withdrawal(self):
        """تأكيد الانقطاع مع غرامة"""
        self.ensure_one()
        if self.apply_fine and self.withdrawal_fine <= 0:
            raise ValidationError(_("Fine amount must be greater than zero."))
        
        self.order_id.write({
            'enrolment_status': 'withdrawn',
            'apply_fine': self.apply_fine,
            'withdrawal_fine': self.withdrawal_fine if self.apply_fine else 0.0
        })
        
        updated_invoice = self.order_id._update_existing_invoice_for_withdrawal()
        
        fine_msg = f"<br/>- Withdrawal Fine: {self.withdrawal_fine}" if self.apply_fine else ""
        self.order_id.message_post(
            body=_("Student has been withdrawn.<br/>"
                "- Existing invoice updated (not replaced)<br/>"
                "- Remaining balance set to %s%s") % (
                    self.withdrawal_fine if self.apply_fine else 0.0, fine_msg),
            subject=_("Withdrawal Processed")
        )
        
        fine_text = f"\nWithdrawal Fine: {self.withdrawal_fine}" if self.apply_fine else ""
        message = _('Student withdrawn successfully.\n'
                'Existing invoice updated.\n'
                'Invoice: %s%s') % (updated_invoice.name, fine_text)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_withdraw_without_fine(self):
        """الانقطاع بدون غرامة"""
        self.ensure_one()
        
        self.order_id.write({
            'enrolment_status': 'withdrawn',
            'apply_fine': False,
            'withdrawal_fine': 0.0
        })
        
        updated_invoice = self.order_id._update_existing_invoice_for_withdrawal()
        
        self.order_id.message_post(
            body=_("Student has been withdrawn without fine.<br/>"
                "- Existing invoice updated (not replaced)<br/>"
                "- Remaining balance set to 0.00"),
            subject=_("Withdrawal Processed")
        )
        
        message = _('Student withdrawn successfully without fine.\n'
                'Existing invoice updated.\n'
                'Invoice: %s') % updated_invoice.name
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }


class SaleOrderPopupWizard(models.TransientModel):
    _name = 'sale.order.popup.wizard'
    _description = 'Popup showing details after order confirmation'
    
    order_id = fields.Many2one('sale.order', string="Order")
    university_id = fields.Char(string="Student ID")
    program_type = fields.Selection([
        ('course', 'Course'),
        ('diploma', 'Diploma')
    ], string="Program Type")
    year = fields.Char(string="Year")
    semester = fields.Selection(related='order_id.order_line.semester', string="Semester")
    product_ids = fields.Many2many(
        'product.product',
        string="Products",
        compute="_compute_product_ids",
        store=False
    )

    @api.depends('order_id.order_line.product_id')
    def _compute_product_ids(self):
        for rec in self:
            if rec.order_id:
                rec.product_ids = rec.order_id.order_line.mapped('product_id')
            else:
                rec.product_ids = False