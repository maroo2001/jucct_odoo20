from odoo import models, fields, tools

class EducationalStudentReport(models.Model):
    _name = "educational.student.report"
    _description = "Educational Student Analysis Report"
    _auto = False 
    _rec_name = 'student_id'

    order_id = fields.Many2one('sale.order', string='Order', readonly=True, aggregator='count_distinct')
    
    confirmed_students = fields.Integer(string='Confirmed Students', readonly=True, aggregator='sum')
    withdrawn_students = fields.Integer(string='Withdrawn Students', readonly=True, aggregator='sum')
    withdrawal_fine_sum = fields.Float(string='Withdrawal Fine', readonly=True, aggregator='sum')
    total_paid = fields.Float(string='Total Paid', readonly=True, aggregator='sum')
    
    program_price = fields.Float(string='Program Price', readonly=True, aggregator='avg')
    remaining_balance = fields.Float(string='Remaining Balance', readonly=True, aggregator='sum')
    
    student_id = fields.Many2one('res.partner', string='Student', readonly=True)
    country_id = fields.Many2one('res.country', string='Country', readonly=True)
    enrolment_status = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed'), ('withdrawn', 'Withdrawn')], string="Enrolment Status", readonly=True)
    program_type = fields.Selection([('course', 'Course'), ('diploma', 'Diploma')], string="Program Type", readonly=True)
    product_id = fields.Many2one('product.product', string='Program/Course', readonly=True)
    academy_id = fields.Many2one('res.partner', string='Academy (SO Line)', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        query = """
            CREATE OR REPLACE VIEW educational_student_report AS (
                SELECT
                    sol.id AS id,
                    so.id AS order_id,
                    
                    CASE WHEN so.enrolment_status = 'confirmed' THEN 1 ELSE 0 END AS confirmed_students,
                    CASE WHEN so.enrolment_status = 'withdrawn' THEN 1 ELSE 0 END AS withdrawn_students,
                    
                    COALESCE((
                        SELECT SUM(COALESCE(am.withdrawal_fine, 0))
                        FROM account_move am
                        INNER JOIN sale_order_line_invoice_rel solir ON solir.invoice_line_id IN (
                            SELECT id FROM account_move_line WHERE move_id = am.id
                        )
                        WHERE solir.order_line_id = sol.id
                            AND am.state = 'posted'
                            AND am.move_type = 'out_invoice'
                    ), 0) AS withdrawal_fine_sum,
                    
                    -- 
                    COALESCE((
                        SELECT SUM(am.amount_total - am.amount_residual - COALESCE(am.withdrawal_fine,0))
                        FROM account_move am
                        INNER JOIN sale_order_line_invoice_rel solir ON solir.invoice_line_id IN (
                            SELECT id FROM account_move_line WHERE move_id = am.id
                        )
                        WHERE solir.order_line_id = sol.id
                            AND am.state = 'posted'
                            AND am.move_type = 'out_invoice'
                            AND COALESCE(am.is_penalty_invoice, FALSE) = FALSE 
                    ), 0) AS total_paid,
                    
                    sol.price_unit AS program_price,
                    
                    --    (remaining_balance) 
                    COALESCE((
                        SELECT SUM(
                            CASE 
                                WHEN am.is_withdraw = TRUE THEN COALESCE(am.withdrawal_fine, 0)
                                ELSE am.amount_residual
                            END
                        )
                        FROM account_move am
                        INNER JOIN sale_order_line_invoice_rel solir ON solir.invoice_line_id IN (
                            SELECT id FROM account_move_line WHERE move_id = am.id
                        )
                        WHERE solir.order_line_id = sol.id
                            AND am.state = 'posted'
                            AND am.move_type = 'out_invoice'
                    ), 0) AS remaining_balance,
                    
                    so.partner_id AS student_id,
                    rp.country_id AS country_id,
                    so.enrolment_status AS enrolment_status,
                    so.program_type AS program_type,
                    sol.product_id AS product_id,
                    sol.academy_id AS academy_id,
                    so.currency_id AS currency_id

                FROM sale_order_line sol
                INNER JOIN sale_order so ON so.id = sol.order_id
                INNER JOIN res_partner rp ON rp.id = so.partner_id
                WHERE so.is_enrolment = TRUE 
                    AND so.state IN ('sale', 'done', 'draft', 'cancel')
            )
        """
        self.env.cr.execute(query)