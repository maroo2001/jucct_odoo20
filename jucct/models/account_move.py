from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta

class AccountMove(models.Model):
    _inherit = 'account.move'
    
    program_type = fields.Selection([('course','Course'),('diploma','Diploma')], string="Program Type" ,default='course')
    is_enrollment = fields.Boolean(string='Is Enrollment Invoice', default=False)
    university_id = fields.Char(string="Student ID" ,default="N/A")
    created_by= fields.Many2one('res.users', string="Created By", default=lambda self: self.env.user.id, store=True)
    is_withdraw = fields.Boolean()
    withdrawal_fine = fields.Float(string="Withdrawal Fine", help="Fine amount for student withdrawal")
    payment_plan = fields.Selection([('full','Full Payment by the end of program/semester'),('payment term','custom payment term')],default='full', string="Payment Plan")
    is_delayed = fields.Boolean(string="Is Payment Delayed", default=False)
    delay_ids = fields.One2many(
        'account.move.payment.delay',
        'move_id',
        string="Payment Delays"
    )
    payment_plan_details = fields.Html(
    string=_("Payment Plan Details"),
    compute='_compute_payment_plan_details',)
    show_payment_plan = fields.Boolean(
    string=_("Show Payment Plan"),
    default=False
)
    
    academy_id = fields.Many2one(
        'res.partner', 
        string='Academy',
        compute='_compute_academy_id',
        store=True
    )
    has_late_payments = fields.Boolean(
    string="Has Late Payments",
    store=True
)
    @api.depends(
        'payment_plan',
        'invoice_payment_term_id',
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.class_offering_id.start_date',
        'invoice_line_ids.class_offering_id.end_date',
        'program_type',
        'delay_ids'
    )
    def _compute_payment_plan_details(self):
        for move in self:
            move.payment_plan_details = ""
            move.has_late_payments = False 
            rows = []

            if not move.invoice_line_ids:
                continue

            offering = move.invoice_line_ids[0].class_offering_id
            if not offering or not offering.start_date or not offering.end_date:
                continue

            total_amount = sum(move.invoice_line_ids.mapped('price_subtotal'))
            start = offering.start_date
            end = offering.end_date
            today = fields.Date.today()

            # =====================================================
            # 1️⃣ PAYMENT TERM (Odoo default)
            # =====================================================
            if move.payment_plan == 'payment term' and move.invoice_payment_term_id:
                base_date = move.invoice_date or today

                for line in move.invoice_payment_term_id.line_ids.sorted('id'):
                    if line.value == 'percent':
                        amount = total_amount * (line.value_amount / 100.0)
                    elif line.value == 'fixed':
                        amount = line.value_amount
                    else:
                        amount = total_amount - sum(r['amount'] for r in rows)

                    due_date = base_date + relativedelta(days=line.nb_days)

                    rows.append({
                        _('label'): move.invoice_payment_term_id.name,
                        _('amount'): amount,
                        _('due_date'): due_date,
                    })

            # =====================================================
            # 2️⃣ COURSE → monthly (date-based names)
            # =====================================================
            elif move.program_type == 'course':
                current = start
                months = []

                while current <= end:
                    months.append(current)
                    current += relativedelta(months=1)

                monthly_amount = total_amount / len(months)

                for m in months:
                    due_date = m + relativedelta(months=1) - timedelta(days=1)
                    rows.append({
                        _('label'): m.strftime('%B %Y'),  # 🔥 CHANGED
                        _('amount'): monthly_amount,
                        _('due_date'): due_date,
                    })


            # =====================================================
            # 3️⃣ DIPLOMA → semesters (academic naming)
            # =====================================================
            else:
                cursor = start
                semesters = []

                # Helper to get next semester boundary
                def get_next_semester_boundary(date_obj):
                    year = date_obj.year
                    month = date_obj.month
                    
                    if month >= 9:  # September or later
                        # First semester: Sep → Jan (next year)
                        if month >= 9 and month <= 12:
                            next_year = year + 1
                        else:
                            next_year = year
                        next_boundary = date(next_year, 1, 29)  # End of January
                        label = _("First Semester %s/%s") % (year, year + 1)
                        duration = 4  # Sep to Jan (4 months)
                    elif month >= 5:  # May to August
                        # Summer semester: May → Jul
                        next_boundary = date(year, 8, 27)  # End of July
                        label = _("Summer Semester %s/%s") % (year - 1, year)
                        duration = 2  # May to Jul (2 months)
                    else:  # January to April
                        # Second semester: Jan → May
                        next_boundary = date(year, 6, 18)  # End of May
                        label = _("Second Semester %s/%s") % (year - 1, year)
                        duration = 4  # Jan to May (4 months)
                    
                    return label, next_boundary, duration

                # Add a safety counter to prevent infinite loops
                max_semesters = 20  # Maximum reasonable number of semesters
                semester_count = 0
                
                while cursor < end and semester_count < max_semesters:
                    # Get the appropriate semester boundary for current cursor position
                    label, semester_end, duration = get_next_semester_boundary(cursor)
                    
                    # Don't exceed the overall end date
                    if semester_end > end:
                        semester_end = end
                    
                    # Avoid zero-length semesters
                    if cursor >= semester_end:
                        # Move to next month to avoid getting stuck
                        cursor = cursor + relativedelta(months=1)
                        continue
                    
                    semesters.append((label, cursor, semester_end, duration))
                    
                    # Move cursor to next day after semester end
                    cursor = semester_end + relativedelta(days=1)
                    semester_count += 1
                
                # If no semesters were created, create one for the entire period
                if not semesters:
                    label = _("Complete Program %s") % start.year
                    semesters.append((label, start, end, 4))
                
                # --------------------------------
                # Amount calculation
                # Summer = half semester
                # --------------------------------
                full_semesters = sum(1 for s in semesters if s[3] == 4)
                summer_semesters = sum(1 for s in semesters if s[3] == 2)
                
                # Handle case where we have only partial semesters
                total_weight = full_semesters + (summer_semesters * 0.5)
                if total_weight > 0:
                    base_amount = total_amount / total_weight
                else:
                    base_amount = total_amount
                
                for label, s_start, s_end, duration in semesters:
                    amount = base_amount if duration == 4 else base_amount / 2
                    
                    # Adjust label for partial semester if it's shorter than expected
                    expected_months = 4 if duration == 4 else 2
                    actual_months = (s_end.year - s_start.year) * 12 + (s_end.month - s_start.month)
                    
                    rows.append({
                        'label': label,
                        'amount': round(amount, 2),
                        'due_date': s_end,
                    })
            # =====================================================
            # 4️⃣ Apply delays
            # =====================================================
            for delay in move.delay_ids:
                for row in rows:
                    if row['due_date'] >= delay.approval_date:
                        row['due_date'] += timedelta(days=delay.delay_days)

            # =====================================================
            # 5️⃣ Link payments & detect lateness
            # =====================================================
            # ---------------------------------
            # Cache payment matches once
            # ---------------------------------
            receivable_lines = move.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable'
            )

            total_paid = sum(
                m.amount
                for line in receivable_lines
                for m in (line.matched_debit_ids + line.matched_credit_ids)
            )
            remaining_pool = total_paid

            for row in rows:
                if remaining_pool <= 0:
                    paid = 0
                else:
                    paid = min(row['amount'], remaining_pool)

                remaining_pool -= paid
                remaining = row['amount'] - paid

                row['paid'] = round(paid, 2)
                row['remaining'] = round(remaining, 2)
                row['late'] = remaining > 0 and row['due_date'] < today
                if row['late']:
                    move.has_late_payments = True
            # =====================================================
            # 6️⃣ HTML Rendering
            # =====================================================
            html = _("""
            <table class="table table-sm o_report_table w-100" style="width:100%;">
                <thead>
                    <tr style="border-bottom:1px solid #000;">
                        <th>Period</th>
                        <th>Due Date</th>
                        <th class="text-right">Amount</th>
                        <th class="text-right">Paid</th>
                        <th class="text-right">Remaining</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
            """)

            for r in rows:
                status = _("Late") if r['late'] else (_("Paid") if r['remaining'] == 0 else _("Unpaid"))
                color = "#f8d7da" if r['late'] else ""

                html += f"""
                <tr style="background-color:{color}">
                    <td>{r['label']}</td>
                    <td>{r['due_date'].strftime('%Y-%m-%d')}</td>
                    <td>{r['amount']:.2f}</td>
                    <td>{r['paid']:.2f}</td>
                    <td>{r['remaining']:.2f}</td>
                    <td>{status}</td>
                </tr>
                """

            html += "</tbody></table>"

            if move.delay_ids:
                html += _("<p><b>Delays Applied:</b></p><ul>")
                for d in move.delay_ids:
                    html += _("<li>%s days approved on %s</li>") % (d.delay_days,d.approval_date)
                html += "</ul>"

            move.payment_plan_details = html


    def toggle_payment_plan(self):
        self.ensure_one()
        self.show_payment_plan = not self.show_payment_plan

    # Fix: "account.payment"."program_type" field is undefined.
    # The parent action (dashboard / student card) carries context['list_view_ref'] =
    # 'jucct.view_move_list_inherit_program_fields' (an account.move list view). Odoo forwards that
    # context to the "Payments" smart button, so the account.payment list tried to use the
    # account.move list view. We strip the view refs so account.payment uses its own views.
    def open_payments(self):
        ctx = {
            k: v for k, v in self.env.context.items()
            if k not in ('list_view_ref', 'form_view_ref', 'kanban_view_ref', 'search_view_ref')
        }
        return super(AccountMove, self.with_context(ctx)).open_payments()

    def action_delay(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Delay Payment'),
            'res_model': 'account.move.payment.delay',
            'target': 'new',
            'editable': 'bottom',
            'view_mode': 'list,form',
            'context': {
                'default_move_id': self.id,
                'default_approval_date': fields.Date.today(),
            },
            'domain': [('move_id', '=', self.id)],
        }
        

    @api.depends('invoice_line_ids.academy_id')
    def _compute_academy_id(self):
        """Get academy from invoice lines"""
        for move in self:
            academies = move.invoice_line_ids.mapped('academy_id')
            move.academy_id = academies[0] if academies else False
            
    status_in_payment = fields.Selection(
        selection_add=[('withdrawn','Withdrawn')])
    amount_paid = fields.Monetary(
        string="Paid Amount",
        compute="_compute_amount_paid",
        store=False,
        currency_field='currency_id'
    )
    amount_due_with = fields.Monetary(
        string="Posted Amount",
        compute="_compute_amount_with",
        currency_field='currency_id',
        store=False
    )
    amount_enrollment=fields.Monetary(
        string="Posted Amount",
        compute= "_compute_amount_enrollment",
        currency_field='currency_id',
        store=False)

    def _get_jucct_paid_amount(self):
        """Paid amount from reconciliation AND from registered payments.

        In Odoo 20 a registered payment can leave amount_residual untouched
        (invoice stays 'In Payment'), so also count the linked payments.
        """
        self.ensure_one()
        if self.state != 'posted':
            return 0.0
        by_residual = self.amount_total - self.amount_residual
        by_payments = 0.0
        for pay in self.matched_payment_ids.filtered(
                lambda p: p.state not in ('draft', 'canceled', 'rejected')):
            by_payments += pay.currency_id._convert(
                pay.amount, self.currency_id, self.company_id,
                pay.date or fields.Date.today())
        return min(max(by_residual, by_payments), self.amount_total)

    def _compute_amount_with(self):
        for rec in self:
            rec.amount_due_with = 0.0 if rec.is_withdraw else rec.amount_total - rec._get_jucct_paid_amount()

    def _compute_amount_paid(self):
        for move in self:
            move.amount_paid = move._get_jucct_paid_amount()

    def _compute_amount_enrollment(self):
        for move in self:
            move.amount_enrollment = move.amount_due_with + move.amount_paid
    @api.depends('payment_state', 'state')
    def _compute_status_in_payment(self):
            super()._compute_status_in_payment()
            for move in self:
                move.status_in_payment = 'withdrawn' if move.is_withdraw else move.payment_state
    
   
    def action_print_pdf(self):
        self.ensure_one()
        if self.is_enrollment:
            return self.env.ref('jucct.enrollment_invoice_report').report_action(self)
        return super().action_print_pdf()

        
# ============================================================
# 
# ============================================================

    settlement_id = fields.Many2one(
        'academy.financial.settlement',
        string='Financial Settlement',
        ondelete='set null'
    )
    
    is_penalty_invoice = fields.Boolean(
        string='Is Penalty Invoice',
        default=False,
        help='Check this if this invoice is for a withdrawal penalty'
    )
    def action_view_source_sale_orders(self):
        if self.is_enrollment:
            sale_orders = self.mapped('invoice_line_ids.sale_line_ids.order_id')
            if not sale_orders:
                raise UserError("No related sale orders found for this invoice.")
            
            action = self.env.ref('jucct.enrollment_jucct_action').sudo().read()[0]

            if len(sale_orders) > 1:
                action['domain'] = [('id', 'in', sale_orders.ids)]
            else:
                action['views'] = [(self.env.ref('jucct.enrollment_jucct_form_view').id, 'form')]
                action['res_id'] = sale_orders.id

            return action

        return super().action_view_source_sale_orders()
    
    def _get_mail_template(self):

        if self.is_enrollment:
            return self.env.ref(
                'jucct.email_template_enrollment_invoice').with_context(lang=self.env.lang)
        return super()._get_mail_template()

    
class AccountMovePaymentDelay(models.Model):
    _name = 'account.move.payment.delay'
    _description = 'Invoice Payment Delay'

    move_id = fields.Many2one('account.move', required=True, ondelete='cascade')
    approval_date = fields.Date(required=True)
    delay_days = fields.Integer(required=True)
    reason = fields.Text()