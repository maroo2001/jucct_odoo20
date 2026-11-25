from odoo import models, fields, tools

class EducationalEnrollmentReport(models.Model): 
    _name = "educational.enrollment.report"
    _description = "Educational Enrollment Report (SQL View)"
    _auto = False
    _rec_name = 'id'

    student_id = fields.Many2one('res.partner', string='Student', readonly=True)
    academy_id = fields.Many2one('res.partner', string='Academy', readonly=True)
    course_id = fields.Many2one('product.template', string='Diploma/course', readonly=True)
    enrollment_date = fields.Date(string='Enrollment Date', readonly=True)
    program_type = fields.Selection([('course', 'Course'), ('diploma', 'Diploma')], string='Program Type', readonly=True)

    enrollment_count = fields.Integer(string='Confirmed Enrollments', readonly=True, aggregator='sum')
    withdrawn_students = fields.Integer(string='Withdrawn Students', readonly=True, aggregator='sum')
    paid_amount = fields.Float(string='Total Paid', readonly=True, aggregator='sum')
    withdrawal_fine = fields.Float(string='Withdrawal Fine', readonly=True, aggregator='sum')
    
    
    program_price = fields.Float(string='Program Price', readonly=True, aggregator='avg') 
    remaining_balance = fields.Float(string='Remaining Balance', readonly=True, aggregator='sum') 
    
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        query = f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    row_number() over() as id,
                    so.partner_id AS student_id,
                    sol.academy_id AS academy_id,
                    pp.product_tmpl_id AS course_id,
                    so.date_order::date AS enrollment_date,
                    pt.program_type AS program_type,
                    COUNT(so.id) AS enrollment_count,
                    SUM(CASE WHEN so.enrolment_status = 'withdrawn' THEN 1 ELSE 0 END) AS withdrawn_students,
                    
                    -- 
                    COALESCE((
                        SELECT SUM(am.amount_total - am.amount_residual - COALESCE(am.withdrawal_fine, 0))
                        FROM account_move am
                        INNER JOIN account_move_line aml ON aml.move_id = am.id
                        INNER JOIN sale_order_line_invoice_rel solir ON solir.invoice_line_id = aml.id
                        WHERE solir.order_line_id = sol.id
                            AND am.state = 'posted' 
                            AND am.move_type = 'out_invoice'
                            AND COALESCE(am.is_penalty_invoice, FALSE) = FALSE
                    ), 0) AS paid_amount,
                    
                    --  (withdrawal_fine)
                    COALESCE((
                        SELECT SUM(COALESCE(am.withdrawal_fine, 0))
                        FROM account_move am
                        INNER JOIN account_move_line aml ON aml.move_id = am.id
                        INNER JOIN sale_order_line_invoice_rel solir ON solir.invoice_line_id = aml.id
                        WHERE solir.order_line_id = sol.id
                            AND am.state = 'posted' 
                            AND am.move_type = 'out_invoice'
                    ), 0) AS withdrawal_fine,
                    
                    -- (program_price) - 
                    sol.price_unit AS program_price, 
                    
                    -- (remaining_balance)
                    COALESCE((
                        SELECT SUM(
                            CASE 
                                WHEN am.is_withdraw = TRUE THEN COALESCE(am.withdrawal_fine, 0)
                                ELSE am.amount_residual
                            END
                        )
                        FROM account_move am
                        INNER JOIN account_move_line aml ON aml.move_id = am.id
                        INNER JOIN sale_order_line_invoice_rel solir ON solir.invoice_line_id = aml.id
                        WHERE solir.order_line_id = sol.id
                            AND am.state = 'posted' 
                            AND am.move_type = 'out_invoice'
                    ), 0) AS remaining_balance
                    
                FROM 
                    sale_order_line sol
                INNER JOIN 
                    sale_order so ON so.id = sol.order_id AND so.is_enrolment = TRUE
                INNER JOIN
                    product_product pp ON pp.id = sol.product_id
                INNER JOIN 
                    product_template pt ON pt.id = pp.product_tmpl_id
                WHERE
                    so.state != 'cancel'
                GROUP BY 
                    so.partner_id, 
                    sol.academy_id, 
                    pp.product_tmpl_id, 
                    so.date_order::date, 
                    pt.program_type,
                    sol.id, 
                    so.id,
                    sol.price_unit --       
            )
        """
        self.env.cr.execute(query)