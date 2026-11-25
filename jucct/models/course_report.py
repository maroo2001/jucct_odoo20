from odoo import models, fields, tools

class CourseReport(models.Model): 
    _name = "educational.course.report"
    _description = "Course Enrollment Analysis Report"
    _auto = False
    _rec_name = 'program_name'

    # id = fields.Integer(readonly=True)
    program_id = fields.Many2one('product.template', string='Program/Course', readonly=True)
    program_name = fields.Char(string='Program Name', readonly=True)
    program_type = fields.Selection([('course', 'Course'), ('diploma', 'Diploma')], string='Program Type', readonly=True)
    academy_id = fields.Many2one('res.partner', string='Academy', readonly=True)
    program_status = fields.Selection([
        ("active", "Active"), ("expired", "Expired"), ("pending", "Pending")
    ], string="Program Status", readonly=True)
    location = fields.Selection(
            [("inside", "Inside"), ("online", "Online"), ("outside", "Outside")],
            string='Location', 
            readonly=True
        )
    enrolment_count = fields.Integer(string='Total Enrollments', readonly=True, aggregator='sum')
    price = fields.Float(string='Program Price', readonly=True, aggregator='sum')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        query = """
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER () AS id,
                    p.id AS program_id,
                    COALESCE(p.name->>'en_US', p.name->>'ar_001', p.name::TEXT) AS program_name,
                    p.program_type AS program_type,
                    p.status AS program_status,
                    apo.academy_id AS academy_id,
                    p.venue AS location,
                    COUNT(sol.id) AS enrolment_count,
                    CASE 
                        WHEN apo.price IS NOT NULL AND apo.price > 0 THEN apo.price
                        ELSE p.list_price
                    END AS price
                FROM 
                    product_template p
                LEFT JOIN 
                    academy_program_offering apo ON apo.program_id = p.id
                LEFT JOIN 
                    product_product pp ON pp.product_tmpl_id = p.id
                LEFT JOIN 
                    sale_order_line sol ON sol.product_id = pp.id
                LEFT JOIN 
                    sale_order so ON so.id = sol.order_id AND so.is_enrolment = TRUE
                WHERE 
                    p.is_program = TRUE
                    AND NOT EXISTS (
                        SELECT 1 FROM ir_model_data imd 
                        WHERE imd.model = 'product.template' 
                        AND imd.res_id = p.id
                    )
                    AND COALESCE(p.name->>'en_US', p.name->>'ar_001', p.name::TEXT) NOT ILIKE '%%Event Registration%%'
                GROUP BY 
                    p.id, p.name, p.program_type, p.status, apo.academy_id, p.list_price, p.venue, apo.price
            )
        """ % (self._table,)
        self.env.cr.execute(query)