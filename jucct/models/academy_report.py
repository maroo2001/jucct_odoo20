from odoo import models, fields, tools

class AcademyPerformanceReport(models.Model):
    _name = "academy.performance.report"
    _description = "Academy Performance Analysis Report (SQL View)"
    _auto = False
    _rec_name = 'academy_id'

    # Fields for the report
    responsible_user_id = fields.Many2one('res.users', string="Responsible User", readonly=True) 
    academy_id = fields.Many2one('res.partner', string="Academy", readonly=True)
    program_id = fields.Many2one('product.template', string="Program", readonly=True)
    total_enrollments = fields.Integer(string="Total Enrollments", readonly=True, aggregator='sum')
    commission_rate = fields.Float(string="Commission Rate (%)", readonly=True, aggregator='avg')  # ← غيرنا إلى avg
    
    # ✅ الحقل المضاف: program_type (يجب أن يكون موجودًا في الـ SQL View)
    program_type = fields.Selection([
        ('course', 'Course'), 
        ('diploma', 'Diploma')
    ], string="Program Type", readonly=True) 

    # -------------------------------------------------------------------------
    # SQL View Definition 
    # -------------------------------------------------------------------------
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        query = """
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER () AS id,
                    ac.responsible_employee_id AS responsible_user_id,
                    apo.academy_id AS academy_id,
                    apo.program_id AS program_id,

                    -- Program type from product_template
                    pt.program_type AS program_type,

                    COUNT(so.id) AS total_enrollments,
                    COALESCE(ac.revenue_share, 0) AS commission_rate
                FROM
                    academy_program_offering apo
                LEFT JOIN
                    res_partner rp ON rp.id = apo.academy_id AND rp.edu_type = 'academy'
                LEFT JOIN
                    academy_contract ac ON ac.id = rp.current_contract_id
                LEFT JOIN
                    product_template pt ON pt.id = apo.program_id
                LEFT JOIN
                    product_product pp ON pp.product_tmpl_id = pt.id
                LEFT JOIN
                    sale_order_line sol
                        ON sol.academy_id = apo.academy_id
                        AND sol.product_id = pp.id
                LEFT JOIN
                    sale_order so
                        ON so.id = sol.order_id
                        AND so.is_enrolment = TRUE
                        AND so.state IN ('sale', 'done')
                WHERE
                    apo.id IS NOT NULL
                GROUP BY
                    apo.academy_id,
                    apo.program_id,
                    pt.program_type,
                    ac.responsible_employee_id,
                    ac.revenue_share
            )
        """ % (self._table,)
        self.env.cr.execute(query)