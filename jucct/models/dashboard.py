
# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import timedelta
from itertools import groupby
from collections import defaultdict


class Dashboard(models.AbstractModel):
    _name = 'educational.dashboard'
    _description = 'Dashboard for Educational Center'

    @api.model
    def get_xmlid_res_id(self, xmlid):
        """Public helper for the JS dashboard (private ``_xmlid_to_res_id`` cannot be called over RPC)."""
        return self.env['ir.model.data']._xmlid_to_res_id(xmlid, raise_if_not_found=False) or False

    @api.model
    def _legacy_read_group(self, model, domain, groupby_field, sum_fields=()):
        """Compatibility wrapper around ``_read_group`` (Odoo 19/20).

        ``read_group`` is deprecated since Odoo 18.2. This returns the same shape the dashboard
        code was written against: a list of dicts ``{groupby_field: (id, display_name) | False,
        '__count': n, <sum_field>: total}``.
        """
        aggregates = ['__count'] + ['%s:sum' % f for f in sum_fields]
        rows = model._read_group(domain, [groupby_field], aggregates)
        result = []
        for row in rows:
            record = row[0]
            item = {
                groupby_field: (record.id, record.display_name) if record else False,
                '__count': row[1],
            }
            for fname, value in zip(sum_fields, row[2:]):
                item[fname] = value
            result.append(item)
        return result

    @api.model
    def get_top_offering_entities(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        """
        Return top 5 entities by number of offerings with:
        - name
        - num_distinct_programs (number of distinct offered programs)
        - num_offerings (count of offerings)
        - id (academy/trainer id where applicable)
        - model ('res.partner' for academy/trainer, 'location' for location rows)
        Grouped by:
        - academies (offering.academy_id)
        - locations (derived from offering.session_ids.location)
        - trainers (derived from offering.session_ids.trainer_id, fallback to offering.academy_trainer_ids)
        Filters are optional by dates, academy, program.
        """
        Offer = self.env['academy.program.offering']

        # Base domain for offerings
        domain = [('status', '=', 'active')]
        if start_date and end_date:
            domain += [
            ('start_date', '<=', end_date),
            ('end_date', '>=', start_date),
            ]
        if academy_id:
            domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            domain += [('session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            domain += [('program_id.venue', '=', location)]

        offers = Offer.search(domain)
        field_info = dict(self.env['product.template']._fields['venue'].get_description(self.env))
        field_selection = dict(field_info.get('selection'))
        # Aggregations
        by_academy = {}
        by_location = {}
        by_trainer = {}

        for off in offers:
            prog_id = off.program_id.id if off.program_id else None

            # Academy aggregation
            if off.academy_id:
                aid = off.academy_id.id
                aentry = by_academy.setdefault(aid, {
                    'id': aid,
                    'name': off.academy_id.name,
                    'model': 'res.partner',
                    'num_offerings': 0,
                    'programs': set(),
                })
                aentry['num_offerings'] += 1
                if prog_id:
                    aentry['programs'].add(prog_id)

            # Locations from sessions' location strings
            locs = set()
            for ss in off.program_id:

                loc = (getattr(ss, 'venue', '') or '')
                loc = field_selection.get(loc, loc)
                if loc:
                    locs.add(loc)
            # If no session location, no location bucket increment
            if locs:
                for loc in locs:
                    lentry = by_location.setdefault(loc, {
                        'id': None,
                        'name': loc,
                        'model': 'academy.program.offering',
                        'num_offerings': 0,
                        'programs': set(),
                    })
                    lentry['num_offerings'] += 1
                    if prog_id:
                        lentry['programs'].add(prog_id)

            # Trainers from sessions; fallback to offering.academy_trainer_ids if no sessions with trainers
            tset = set()
            sess_trainers = [s.trainer_id.id for s in off.session_ids if s.trainer_id]
            if sess_trainers:
                tset.update(sess_trainers)

            for tid in tset:
                partner = self.env['res.partner'].browse(tid)
                tentry = by_trainer.setdefault(tid, {
                    'id': tid,
                    'name': partner.name,
                    'model': 'academy.program.offering',
                    'num_offerings': 0,
                    'programs': set(),
                })
                tentry['num_offerings'] += 1
                if prog_id:
                    tentry['programs'].add(prog_id)

        def finalize_and_top(mapping, key_sort, topn=5):
            rows = []
            for k, v in mapping.items():
                rows.append({
                    'id': v.get('id'),
                    'name': v.get('name'),
                    'model': v.get('model'),
                    'num_offerings': int(v.get('num_offerings', 0)),
                    'num_distinct_programs': int(len(v.get('programs', set()))),
                })
            rows.sort(key=lambda r: (r[key_sort], r['num_distinct_programs']), reverse=True)
            # add rank
            out = []
            for idx, r in enumerate(rows[:topn], start=1):
                r2 = dict(r)
                r2['rank'] = idx
                out.append(r2)
            return out

        result = {
            'academies': finalize_and_top(by_academy, 'num_offerings'),
            'locations': finalize_and_top(by_location, 'num_offerings'),
            'trainers': finalize_and_top(by_trainer, 'num_offerings'),
        }
        return result

    @api.model
    def get_dashboard_data(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        return {
            'academic_overview': self._get_academic_overview(start_date, end_date, academy_id, program_id, trainer_id, location),
            'student_overview': self._get_student_overview(start_date, end_date, academy_id, program_id, trainer_id, location),
            'financial_overview': self._get_financial_overview(start_date, end_date, academy_id, program_id, trainer_id, location),
            'academies_overview': self._get_academies_overview(start_date, end_date, academy_id, program_id, trainer_id, location),
        }

    def _get_academic_overview(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        Product = self.env['product.template']
        Session = self.env['academy.session']
        Offering = self.env['academy.program.offering']

        domain = [('status', '=', 'active')]
        if start_date and end_date:
            domain += [('create_date', '>=', start_date), ('create_date', '<=', end_date)]
        if academy_id:
            domain += [('offering_ids.academy_id', '=', int(academy_id)), ('offering_ids.status', '=', 'active')]
        if program_id:
            domain += [('id', '=', program_id)]
        if trainer_id:
            domain += [('offering_ids.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            domain += [('venue', '=', location)]

        total_active_programs = Product.search_count(domain + [('is_program', '=', True)])
        total_active_courses = Product.search_count(domain + [('program_type', '=', 'course')])
        total_active_diplomas = Product.search_count(domain + [('program_type', '=', 'diploma')])

        session_domain = [('status', '=', 'scheduled'),('record_type', '=', 'session day')]
        if academy_id:
            session_domain += [('academy_id', '=', int(academy_id))]
        if trainer_id:
            session_domain += [('trainer_id', '=', int(trainer_id))]
        if location:
            session_domain += [('location', '=', location)]

        upcoming_sessions = Session.search_count(session_domain +[('session_date', '>=', fields.Date.today()), ('session_date', '<=', fields.Date.today() + timedelta(days=7))])
        if start_date and end_date:
            session_domain += [('session_date', '>=', start_date), ('session_date', '<=', end_date)]
        todays_sessions = Session.search(session_domain + [('session_date', '=', fields.Date.today())])
        todays_schedule = []
        for session in todays_sessions:
            todays_schedule.append({
                'course': session.program_id.name,
                'academy': session.academy_id.name,
                'trainer': session.trainer_id.name,
                'time': f"{session.start_time}:00 - {session.end_time}:00",
            })

        # New: Get data for academy/courses chart
        academy_courses_data = self._get_academy_courses_data(start_date, end_date, academy_id, program_id, trainer_id, location)
        
        # New: Get data for trainer/courses chart
        trainer_courses_data = self._get_trainer_courses_data(start_date, end_date, academy_id, program_id, trainer_id, location)
        
        # New: Get data for location/courses chart
        location_courses_data = self._get_location_courses_data(start_date, end_date, academy_id, program_id, trainer_id, location)

        return {
            'total_active_programs': total_active_programs,
            'total_active_courses': total_active_courses,
            'total_active_diplomas': total_active_diplomas,
            'upcoming_sessions': upcoming_sessions,
            'todays_schedule': todays_schedule,
            'top_5_academies': self._get_top_5_data('academy_id', start_date, end_date, academy_id, program_id, None, trainer_id, location),
            'top_5_courses': self._get_top_5_data('course', start_date, end_date, academy_id, program_id, None, trainer_id, location),
            'top_5_diplomas': self._get_top_5_data('diploma', start_date, end_date, academy_id, program_id, None, trainer_id, location),
            'top_5_locations': self._get_top_5_data('location', start_date, end_date, academy_id, program_id, None, trainer_id, location),
            'top_5_trainers': self._get_top_5_data('trainer', start_date, end_date, academy_id, program_id, None, trainer_id, location),
            # New chart data
            'academy_courses': academy_courses_data,
            'trainer_courses': trainer_courses_data,
            'location_courses': location_courses_data,
        }
    def _get_academy_courses_data(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        """Get data for academy/courses chart using read_group for better performance"""
        Offering = self.env['academy.program.offering']
        
        # Build domain
        domain = [('status', '=', 'active'), ('program_id.program_type', 'in', ['course', 'diploma'])]
        if start_date and end_date:
            domain += [('create_date', '>=', start_date), ('create_date', '<=', end_date)]
        if academy_id:
            domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            domain += [('session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            domain += [('program_id.venue', '=', location)]
        
        # Use read_group to count distinct programs per academy
        results = self._legacy_read_group(Offering, domain, 'academy_id')
        
        # Process results
        labels = []
        values = []
        for result in sorted(results, key=lambda x: x['__count'], reverse=True)[:10]:
            if result['academy_id']:
                labels.append(result['academy_id'][1])  # academy name
                values.append(result['__count'])
        
        return {
            'labels': labels,
            'values': values
        }

    def _get_trainer_courses_data(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        """Get data for trainer/courses chart using read_group for better performance"""
        Session = self.env['academy.session']
        
        # Build domain
        domain = [('program_id.program_type', 'in', ['course', 'diploma']), ('record_type', '=', 'session day')]
        if start_date and end_date:
            domain += [('session_date', '>=', start_date), ('session_date', '<=', end_date)]
        if academy_id:
            domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            domain += [('trainer_id', '=', int(trainer_id))]
        if location:
            domain += [('program_id.venue', '=', location)]
        
        # Use read_group to count distinct programs per trainer
        results = self._legacy_read_group(Session, domain, 'trainer_id')
        
        # Process results
        labels = []
        values = []
        for result in sorted(results, key=lambda x: x['__count'], reverse=True)[:10]:
            if result['trainer_id']:
                labels.append(result['trainer_id'][1])  # trainer name
                values.append(result['__count'])
        
        return {
            'labels': labels,
            'values': values
        }

    def _get_location_courses_data(
        self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None
    ):
        """Get data for location/courses chart using program.venue instead of session.location"""
        Session = self.env['academy.program.offering']

        # Build domain
        domain = [('program_id.program_type', 'in', ['course', 'diploma'])]
        if start_date and end_date:
            domain += [('start_date', '>=', start_date), ('start_date', '<=', end_date)]
        if academy_id:
            domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            domain += [('session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            domain += [('program_id.venue', '=', location)]
        

        # read_group by program_id to reduce records
        results = self._legacy_read_group(Session, domain, 'program_id')

        # Map program_id -> venue
        Program = self.env['product.template']
        program_ids = [r['program_id'][0] for r in results if r.get('program_id')]
        venues = {p.id: p.venue for p in Program.browse(program_ids)}
        field_info = dict(Program._fields['venue'].get_description(self.env))
        selection_dict = dict(field_info.get('selection'))

        # Aggregate by venue
        venue_counts = {}
        for result in results:
            pid = result['program_id'][0] if result.get('program_id') else None
            if not pid:
                continue
            venue = (selection_dict.get(venues.get(pid)) or '').strip()
            if not venue:
                continue
            venue_counts[venue] = venue_counts.get(venue, 0) + result['__count']

        # Sort top 10 by count
        sorted_items = sorted(venue_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        labels = [v[0] for v in sorted_items]
        values = [v[1] for v in sorted_items]

        return {
            'labels': labels,
            'values': values,
        }


    def _get_student_overview(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        Student = self.env['res.partner']
        Enrollment = self.env['sale.order']
        offering = self.env['academy.program.offering']

        # Domain for students
        student_domain = [('edu_type', '=', 'student')]
        student_enrollment_domain = []
      
        if academy_id:
            student_enrollment_domain += [('order_line.academy_id', '=', int(academy_id))]
        if program_id:
            student_enrollment_domain += [('order_line.product_id.product_tmpl_id', '=', int(program_id))]
        if trainer_id:
            student_enrollment_domain += [('order_line.class_offering_id.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            student_enrollment_domain += [('order_line.class_offering_id.program_id.venue', '=', location)]
        
        if student_enrollment_domain:
            enrolled_students = Enrollment.search(student_enrollment_domain + [('is_enrolment', '=', True)]).mapped('partner_id').ids
            student_domain += [('id', 'in', enrolled_students)]
        
        total_students = Student.search_count(student_domain)

        # Domain for enrollments and offerings
        enrollment_domain = [('is_enrolment', '=', True)]
        offering_domain = []
        if start_date and end_date:
            enrollment_domain += [('create_date', '>=', start_date), ('create_date', '<=', end_date)]
            offering_domain += [('create_date', '>=', start_date), ('create_date', '<=', end_date)]
        if academy_id:
            enrollment_domain += [('order_line.academy_id', '=', int(academy_id))]
            offering_domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            enrollment_domain += [('order_line.product_id.product_tmpl_id', '=', int(program_id))]
            offering_domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            enrollment_domain += [('order_line.class_offering_id.session_ids.trainer_id', '=', int(trainer_id))]
            offering_domain += ['|', ('session_ids.trainer_id', '=', int(trainer_id)), ('academy_trainer_ids', 'in', [int(trainer_id)])]
        if location:
            enrollment_domain += [('order_line.class_offering_id.program_id.venue', '=', location)]
            offering_domain += [('program_id.venue', '=', location)]

        # Get new registrations (confirmed enrollments)
        new_registrations = Enrollment.search_count(enrollment_domain + [('enrolment_status', '=', 'confirmed')])
        
        # Get withdrawn students
        withdrawn_students = Enrollment.search_count(enrollment_domain + [('enrolment_status', '=', 'withdrawn')])
        
        # Get completed programs
        completed_domain = offering_domain + [('status', '=', 'expired')]
        if start_date and end_date:
            completed_domain += [('end_date', '>=', start_date), ('end_date', '<=', end_date)]
        completed_programs = offering.search_count(completed_domain)

        # Get trend data
        labels = []
        new_registrations_data = []
        withdrawn_students_data = []
        for i in range(5, -1, -1):
            period_start = fields.Date.today().replace(day=1) - timedelta(days=i*30)
            period_end = period_start + timedelta(days=30)
            labels.append(period_start.strftime('%B %Y'))
            
            # Get registrations for this period
            period_enrollment_domain = enrollment_domain + [
                ('create_date', '>=', period_start),
                ('create_date', '<=', period_end),
                ('enrolment_status', '=', 'confirmed')
            ]
            new_registrations_data.append(Enrollment.search_count(period_enrollment_domain))
            
            # Get withdrawals for this period
            period_withdrawn_domain = enrollment_domain + [
                ('create_date', '>=', period_start),
                ('create_date', '<=', period_end),
                ('enrolment_status', '=', 'withdrawn')
            ]
            withdrawn_students_data.append(Enrollment.search_count(period_withdrawn_domain))


        return {
            'total_students': total_students,
            'new_registrations': new_registrations,
            'withdrawn_students': withdrawn_students,
            'completed_programs': completed_programs,
            'trends': {
                'labels': labels,
                                'new_registrations': new_registrations_data,
                'withdrawn_students': withdrawn_students_data,
            },
           # Top 5 by number of students (enrolments), not by academy share
            'top_5_academies': self._get_top_5_students('academy_id', start_date, end_date, academy_id, program_id, trainer_id, location),
            'top_5_courses': self._get_top_5_students('course', start_date, end_date, academy_id, program_id, trainer_id, location),
            'top_5_diplomas': self._get_top_5_students('diploma', start_date, end_date, academy_id, program_id, trainer_id, location),
            'top_5_locations': self._get_top_5_students('location', start_date, end_date, academy_id, program_id, trainer_id, location),
            'top_5_trainers': self._get_top_5_students('trainer', start_date, end_date, academy_id, program_id, trainer_id, location),

        }

    def _get_financial_overview(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        Invoice = self.env['account.move']
        Settlement = self.env['academy.financial.settlement']

        invoice_domain = [('is_enrollment', '=', True)]
        if start_date and end_date:
            invoice_domain += [('invoice_date', '>=', start_date), ('invoice_date', '<=', end_date)]
        if academy_id:
            invoice_domain += [('invoice_line_ids.academy_id', '=', int(academy_id))]
        if program_id:
            invoice_domain += [('invoice_line_ids.product_id.product_tmpl_id', '=', int(program_id))]
        if trainer_id:
            invoice_domain += [('invoice_line_ids.class_offering_id.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            invoice_domain += [('invoice_line_ids.class_offering_id.program_id.venue', '=', location)]

        total_invoices = Invoice.search_count(invoice_domain + [('payment_state', '!=', 'draft')])
        paid_invoices_records = Invoice.search(invoice_domain + [('payment_state', 'in', ['paid', 'in_payment', 'partial', 'withdrawn'])])
        paid_invoices = len(paid_invoices_records.filtered(lambda i: not i.is_withdraw and i.amount_due_with <= 0))
        unpaid_invoices = total_invoices - paid_invoices
        unpaid_invoices_records = Invoice.search(invoice_domain + [('payment_state', 'not in', ['draft', 'withdrawn'])])
        total_collected = round(sum(paid_invoices_records.mapped('amount_paid')), 2)
        total_unpaid = round(sum(unpaid_invoices_records.mapped('amount_due_with')),2)
        total = round(total_collected + total_unpaid,2)
        settlement_domain = [('settlement_status', '=', 'draft')]
        if start_date and end_date:
            settlement_domain += [('settlement_date', '>=', start_date), ('settlement_date', '<=', end_date)]
        if academy_id:
            settlement_domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            settlement_domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            settlement_domain += [('offering_id.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            settlement_domain += [('offering_id.program_id.venue', '=', location)]

        pending_settlements = Settlement.search(settlement_domain)
        total_pending_settlements = round(sum(pending_settlements.mapped('center_share')),2)

        settlement_domain = [('settlement_status', '=', 'paid')]
        if start_date and end_date:
            settlement_domain += [('settlement_date', '>=', start_date), ('settlement_date', '<=', end_date)]
        if academy_id:
            settlement_domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            settlement_domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            settlement_domain += [('offering_id.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            settlement_domain += [('offering_id.program_id.venue', '=', location)]

        paid_settlements = Settlement.search(settlement_domain + [('is_center_settlement', '=', False)])
        total_paid_settlements = round(sum(paid_settlements.mapped('center_share')),2)

        # Monthly revenue data for the chart
        labels = []
        revenue_data = []
        settlements_data = []
        for i in range(5, -1, -1):
            start_month = fields.Date.today().replace(day=1) - timedelta(days=i*30)
            end_month = start_month + timedelta(days=30)
            month_label = start_month.strftime('%B %Y')
            labels.append(month_label)
            
            # Monthly revenue
            month_invoices = Invoice.search(invoice_domain + [
                ('invoice_date', '>=', start_month),
                ('invoice_date', '<', end_month),
                ('payment_state', 'in', ['paid', 'in_payment', 'partial', 'withdrawn'])
            ])
            revenue_data.append(sum(month_invoices.mapped('amount_paid')))
            
            # Monthly settlements
            month_settlements = Settlement.search([
                ('settlement_status', '=', 'paid'),
                ('settlement_date', '>=', start_month),
                ('settlement_date', '<', end_month)
            ])
            settlements_data.append(sum(month_settlements.mapped('center_share')))
    
        return {
            'total' : total,
            'total_invoices': total_invoices,
            'paid_invoices': paid_invoices,
            'unpaid_invoices': unpaid_invoices,
            'total_collected': total_collected,
            'total_unpaid' : total_unpaid,
            'pending_settlements': len(pending_settlements),
            'total_pending_settlements': total_pending_settlements,
            'total_paid_settlements' : total_paid_settlements,
            'paid_settlements' : len(paid_settlements),
            'top_5_academies': self._get_top_5_data('academy_id', start_date, end_date, academy_id, program_id, True, trainer_id, location),
            'top_5_courses': self._get_top_5_data('course', start_date, end_date, academy_id, program_id, True, trainer_id, location),
            'top_5_diplomas': self._get_top_5_data('diploma', start_date, end_date, academy_id, program_id, True, trainer_id, location),
            'top_5_locations': self._get_top_5_data('location', start_date, end_date, academy_id, program_id, True, trainer_id, location),
            'top_5_trainers': self._get_top_5_data('trainer', start_date, end_date, academy_id, program_id, True, trainer_id, location),
            'currency' : self.env.company.currency_id.symbol,
            'revenue_trends': {
                'labels': labels,
                'revenue': revenue_data,
                'settlements': settlements_data,
            }
            
        }

    def _get_academies_overview(self, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        Academy = self.env['res.partner']
        Settlement = self.env['academy.financial.settlement']

        domain = [('edu_type', '=', 'academy'), ('contract_status', '=', 'active')]
        if academy_id:
            domain += [('id', '=', academy_id)]

        total_active_academies = Academy.search_count(domain)

        settlement_domain = [('settlement_status', '=', 'draft')]
        if start_date and end_date:
            settlement_domain += [('settlement_date', '>=', start_date), ('settlement_date', '<=', end_date)]
        if academy_id:
            settlement_domain += [('academy_id', '=', academy_id)]

        pending_settlements = Settlement.search_count(settlement_domain)

        settlement_domain = [('settlement_status', '=', 'paid')]
        if start_date and end_date:
            settlement_domain += [('settlement_date', '>=', start_date), ('settlement_date', '<=', end_date)]
        if academy_id:
            settlement_domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            settlement_domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            settlement_domain += [('offering_id.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            settlement_domain += [('offering_id.program_id.venue', '=', location)]
        
        paid_settlements = Settlement.search_count(settlement_domain)

        groups = self._legacy_read_group(
            Settlement,
            settlement_domain + [('academy_id', '!=', False)],
            'academy_id', ['academy_share'],
        )

        top_groups = sorted(
            groups,
            key=lambda g: float(g.get('academy_share') or 0.0),
            reverse=True
        )[:3]

        top_3_academies = []
        for g in top_groups:
            acad = g.get('academy_id') or False
            if isinstance(acad, (list, tuple)) and acad:
                acad_id = acad[0]
                acad_name = acad[1] if len(acad) > 1 else self.env['res.partner'].browse(acad_id).name
            elif isinstance(acad, int):
                acad_id = acad
                acad_name = self.env['res.partner'].browse(acad_id).name
            else:
                continue
            revenue = float(g.get('academy_share') or 0.0)
            top_3_academies.append({'id': acad_id, 'name': acad_name, 'revenue': revenue})

        return {
            'total_active_academies': total_active_academies,
            'academies_with_pending_settlements': pending_settlements,
            'paid_settlements' : paid_settlements,
            'top_5_by_offering': self.get_top_offering_entities(start_date, end_date, academy_id, program_id, trainer_id, location),
        }

    def _get_top_5_data(self, entity, start_date=None, end_date=None, academy_id=None, program_id=None, cent=None, trainer_id=None, location=None):
        Settlement = self.env['academy.financial.settlement']
        sessiono = self.env['academy.session']
        # build base domain for settlements
        domain = [('settlement_status', '=', 'paid')]
        if start_date and end_date:
            domain += [('settlement_date', '>=', start_date), ('settlement_date', '<=', end_date)]
        if academy_id:
            domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            domain += [('program_id', '=', int(program_id))]
        if trainer_id:
            domain += [('offering_id.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            domain += [('offering_id.program_id.venue', '=', location)]

        def safe_float(v):
            try:
                return float(v or 0.0)
            except Exception:
                return 0.0

        if cent == None:
            if entity == 'academy_id':
                groups = self._legacy_read_group(Settlement, domain + [('academy_id', '!=', False)], 'academy_id', ['academy_share'])
                top = sorted(groups, key=lambda g: safe_float(g.get('academy_share')), reverse=True)[:5]
                result = []
                for idx, g in enumerate(top, start=1):
                    acad = g.get('academy_id')
                    if not acad:
                        continue
                    # acad can be (id, name) or int depending on Odoo version
                    if isinstance(acad, (list, tuple)):
                        aid, aname = acad[0], acad[1] if len(acad) > 1 else self.env['res.partner'].browse(acad[0]).name
                    else:
                        aid, aname = acad, self.env['res.partner'].browse(acad).name
                    result.append({'id': aid, 'name': aname, 'value': safe_float(g.get('academy_share')), 'rank': idx})
                return result

            # TOP BY PROGRAM (course / diploma)
            if entity in ('course', 'diploma'):
                # filter settlements by linked program type
                domain_prog = list(domain) + [('program_id.program_type', '=', entity)]
                groups = self._legacy_read_group(Settlement, domain_prog + [('program_id', '!=', False)], 'program_id', ['academy_share'])
                top = sorted(groups, key=lambda g: safe_float(g.get('academy_share')), reverse=True)[:5]
                result = []
                for idx, g in enumerate(top, start=1):
                    prog = g.get('program_id')
                    if not prog:
                        continue
                    if isinstance(prog, (list, tuple)):
                        pid, pname = prog[0], prog[1] if len(prog) > 1 else self.env['product.template'].browse(prog[0]).name
                    else:
                        pid, pname = prog, self.env['product.template'].browse(prog).name
                    result.append({'id': pid, 'name': pname, 'value': safe_float(g.get('academy_share')), 'rank': idx, 'model': 'product.template'})
                return result

            # TOP BY LOCATION (sum academy_share grouped by session location derived from offerings' sessions)
            if entity == 'location':
                # Find settlements that reference an offering to use sessions for location
                field_info = dict(sessiono._fields['location'].get_description(self.env))
                selection_dict = dict(field_info.get('selection'))
                settlements = Settlement.search(domain + [('offering_id', '!=', False)])
                city_totals = {}
                for s in settlements:
                    share = safe_float(getattr(s, 'academy_share', 0.0))
                    offering = s.offering_id
                    if not offering:
                        continue
                    # Take distinct session locations (city) from sessions; fallback to academy city on offering
                    sessions = offering.session_ids
                    cities = set()
                    for ss in sessions:
                        # Prefer session's academy city if available, else use offering's academy city
                        city = (ss.location or '').strip()
                        label = selection_dict.get(ss.location) or ''
                        if city:
                            cities.add((city, label))
                    # If no sessions or no cities found, fallback to offering academy city
                    if not cities:
                        continue
                    per_city = share / max(1, len(cities))
                    for c in cities:
                        city_totals[c] = city_totals.get(c, 0.0) + per_city

                top = sorted(city_totals.items(), key=lambda i: i[1], reverse=True)[:5]
                return [{'rank' : idx,'name': c[0], 'label': c[1], 'value': v} for idx, (c, v) in enumerate(top, start=1)]

            # TOP BY TRAINER (sum academy_share for trainers found on offering sessions)
            if entity == 'trainer':
                # get settlements that reference an offering
                settlements = Settlement.search(domain + [('offering_id', '!=', False)])
                trainer_totals = {}
                for s in settlements:
                    try:
                        share = safe_float(s.academy_share)
                    except Exception:
                        share = 0.0
                    offering = s.offering_id
                    if not offering:
                        continue
                    # use sessions on the offering to find trainers
                    sessions = offering.session_ids.filtered(lambda ss: ss.trainer_id)
                    if not sessions:
                        # fallback: if offering has academy_trainer_ids, attribute to those trainers equally
                        trainers = offering.academy_trainer_ids
                        if trainers:
                            per_trainer = share / max(1, len(trainers))
                            for t in trainers:
                                trainer_totals[t.id] = trainer_totals.get(t.id, 0.0) + per_trainer
                        else:
                            continue
                    else:
                        # distribute share among distinct trainers found on sessions
                        distinct_trainers = list({s.trainer_id.id: s.trainer_id for s in sessions if s.trainer_id}.values())
                        if distinct_trainers:
                            per_trainer = share / max(1, len(distinct_trainers))
                            for t in distinct_trainers:
                                trainer_totals[t.id] = trainer_totals.get(t.id, 0.0) + per_trainer

                top = sorted(trainer_totals.items(), key=lambda i: i[1], reverse=True)[:5]
                result = []
                for idx, (tid, val) in enumerate(top, start=1):
                    name = self.env['res.partner'].browse(tid).name
                    result.append({'rank':idx, 'id': tid, 'name': name, 'value': safe_float(val)})
                return result
        if cent == True:
            if entity == 'academy_id':
                groups = self._legacy_read_group(Settlement, domain + [('academy_id', '!=', False)], 'academy_id', ['center_share'])
                top = sorted(groups, key=lambda g: safe_float(g.get('center_share')), reverse=True)[:5]
                result = []
                for idx, g in enumerate(top, start=1):
                    acad = g.get('academy_id')
                    if not acad:
                        continue
                    # acad can be (id, name) or int depending on Odoo version
                    if isinstance(acad, (list, tuple)):
                        aid, aname = acad[0], acad[1] if len(acad) > 1 else self.env['res.partner'].browse(acad[0]).name
                    else:
                        aid, aname = acad, self.env['res.partner'].browse(acad).name
                    result.append({'rank':idx, 'id': aid, 'name': aname, 'value': safe_float(g.get('center_share'))})
                return result

            # TOP BY PROGRAM (course / diploma)
            if entity in ('course', 'diploma'):
                # filter settlements by linked program type
                domain_prog = list(domain) + [('program_id.program_type', '=', entity)]
                groups = self._legacy_read_group(Settlement, domain_prog + [('program_id', '!=', False)], 'program_id', ['center_share'])
                top = sorted(groups, key=lambda g: safe_float(g.get('center_share')), reverse=True)[:5]
                result = []
                for idx, g in enumerate(top, start=1):
                    prog = g.get('program_id')
                    if not prog:
                        continue
                    if isinstance(prog, (list, tuple)):
                        pid, pname = prog[0], prog[1] if len(prog) > 1 else self.env['product.template'].browse(prog[0]).name
                    else:
                        pid, pname = prog, self.env['product.template'].browse(prog).name
                    result.append({'rank' : idx, 'id': pid, 'name': pname, 'value': safe_float(g.get('center_share'))})
                return result

            # TOP BY LOCATION (sum center_share grouped by session location derived from offerings' sessions)
            if entity == 'location':
                field_info = dict(sessiono._fields['location'].get_description(self.env))
                selection_dict = dict(field_info.get('selection'))
                settlements = Settlement.search(domain + [('offering_id', '!=', False)])
                city_totals = {}
                for s in settlements:
                    share = safe_float(getattr(s, 'center_share', 0.0))
                    offering = s.offering_id
                    if not offering:
                        continue
                    sessions = offering.session_ids
                    cities = set()
                    for ss in sessions:

                        city = (ss.location or '').strip()
                        label = selection_dict.get(ss.location) or ''
                        if city:
                            cities.add((city, label))
                    if not cities:
                        continue
                    per_city = share / max(1, len(cities))
                    for c in cities:
                        city_totals[c] = city_totals.get(c, 0.0) + per_city

                top = sorted(city_totals.items(), key=lambda i: i[1], reverse=True)[:5]
                return [{'rank' : idx,'name': c[0], 'label': c[1], 'value': round(v,2)} for idx, (c, v) in enumerate(top, start=1)]

            # TOP BY TRAINER (sum center_share for trainers found on offering sessions)
            if entity == 'trainer':
                # get settlements that reference an offering
                settlements = Settlement.search(domain + [('offering_id', '!=', False)])
                trainer_totals = {}
                for s in settlements:
                    try:
                        share = safe_float(s.center_share)
                    except Exception:
                        share = 0.0
                    offering = s.offering_id
                    if not offering:
                        continue
                    # use sessions on the offering to find trainers
                    sessions = offering.session_ids.filtered(lambda ss: ss.trainer_id)
                    if not sessions:
                        # fallback: if offering has academy_trainer_ids, attribute to those trainers equally
                        trainers = offering.academy_trainer_ids
                        if trainers:
                            per_trainer = share / max(1, len(trainers))
                            for t in trainers:
                                trainer_totals[t.id] = trainer_totals.get(t.id, 0.0) + per_trainer
                        else:
                            continue
                    else:
                        # distribute share among distinct trainers found on sessions
                        distinct_trainers = list({s.trainer_id.id: s.trainer_id for s in sessions if s.trainer_id}.values())
                        if distinct_trainers:
                            per_trainer = share / max(1, len(distinct_trainers))
                            for t in distinct_trainers:
                                trainer_totals[t.id] = trainer_totals.get(t.id, 0.0) + per_trainer

                top = sorted(trainer_totals.items(), key=lambda i: i[1], reverse=True)[:5]
                result = []
                for idx, (tid, val) in enumerate(top, start=1):
                    name = self.env['res.partner'].browse(tid).name
                    result.append({'rank' : idx, 'id': tid, 'name': name, 'value': safe_float(round(val,2))})
                return result

        return []

    def _get_top_5_students(self, entity, start_date=None, end_date=None, academy_id=None, program_id=None, trainer_id=None, location=None):
        """Compute top 5 by number of students (enrolments) for the student tab.
        entity: 'academy_id' | 'course' | 'diploma' | 'location' | 'trainer'
        """
        SaleLine = self.env['sale.order.line']
        SaleOrder = self.env['sale.order']
        Offering = self.env['academy.program.offering']
        Partner = self.env['res.partner']
        ProductTmpl = self.env['product.template']
        # Base domains
        order_domain = [('is_enrolment', '=', True),('enrolment_status','=', 'confirmed')]
        if start_date and end_date:
            order_domain += [('create_date', '>=', start_date), ('create_date', '<=', end_date)]
        line_domain = [('order_id.is_enrolment', '=', True),('order_id.enrolment_status','=', 'confirmed')]
        if start_date and end_date:
            line_domain += [('order_id.create_date', '>=', start_date), ('order_id.create_date', '<=', end_date)]
        if academy_id:
            line_domain += [('academy_id', '=', int(academy_id))]
        if program_id:
            line_domain += [('product_id.product_tmpl_id', '=', int(program_id))]
        if trainer_id:
            line_domain += [('class_offering_id.session_ids.trainer_id', '=', int(trainer_id))]
        if location:
            line_domain += [('class_offering_id.program_id.venue', '=', location)]

        lines = SaleLine.search(line_domain)

        # Helper accumulator structures
        # For academy/course/trainer/location: map entity_key -> set(partner_ids)
        containers = defaultdict(set)
        # For fractional weighting (location/trainer) we accumulate float weights optionally
        weights = defaultdict(float)
        # We'll also keep mapping entity id -> name
        names = {}

        # Identify entity mode
        if entity == 'academy_id':
            # academy stored on the line as academy_id (Many2one res.partner)
            for ln in lines.filtered(lambda l: l.academy_id):
                aid = ln.academy_id.id
                pid = ln.order_id.partner_id.id
                if pid:
                    containers[aid].add(pid)
                    names.setdefault(aid, ln.academy_id.name or str(aid))

        elif entity in ('course', 'diploma'):
            # group by product template (program)
            for ln in lines.filtered(lambda l: l.product_id):
                tmpl = getattr(ln.product_id, 'product_tmpl_id', False)
                if not tmpl:
                    continue
                if tmpl.program_type != entity:
                    continue
                pid = ln.order_id.partner_id.id
                if pid:
                    containers[tmpl.id].add(pid)
                    names.setdefault(tmpl.id, tmpl.name or str(tmpl.id))

        elif entity == 'location':
            # We'll attribute each enrolment line to the set of locations for its offering/program.
            # If multiple locations apply, distribute weight equally (like previous logic).
            field_info = dict(self.env['product.template']._fields['venue'].get_description(self.env))
            field_selection = dict(field_info.get('selection'))
            for ln in lines:
                partner_id = ln.order_id.partner_id.id
                if not partner_id:
                    continue

                # collect locations from offering sessions if line has class_offering_id
                locs = []
                if ln.class_offering_id:
                    off = ln.class_offering_id
                    # session-level locations
                    sess_locs = [field_selection.get(s.location, s.location) for s in off.session_ids.filtered(lambda s: s.location)]
                    locs = list(dict.fromkeys([ (l or '').strip() for l in sess_locs if (l or '').strip() ]))
                    # fallback to academy.city
                    if not locs and off.program_id and getattr(off.program_id, 'venue', False):
                        v = (field_selection.get(off.program_id.venue, off.program_id.venue) or '').strip()
                        if v:
                            locs = [v]
                else:
                    # If no offering, try program attached on line.product or product template
                    if ln.product_id and getattr(ln.product_id, 'product_tmpl_id', False):
                        tmpl = ln.product_id.product_tmpl_id
                        if getattr(tmpl, 'venue', False):
                            v = (field_selection.get(tmpl.venue, tmpl.venue) or '').strip()
                            if v:
                                locs = [v]

                if not locs:
                    # nothing to attribute
                    continue

                weight = 1.0 / max(1, len(locs))
                for loc in locs:
                    containers[loc].add(partner_id)
                    weights[loc] += weight
                    names.setdefault(loc, loc)

            # For location, containers keys are strings (location names), not IDs.

        elif entity == 'trainer':
            # Attribute enrolments to trainers found on the offering's sessions, or fallback to academy_trainer_ids
            for ln in lines:
                partner_id = ln.order_id.partner_id.id
                if not partner_id:
                    continue
                # prefer class_offering_id -> session trainer_ids
                off = ln.class_offering_id or False
                trainers_for_off = []
                if off:
                    sess_trainers = [s.trainer_id for s in off.session_ids.filtered(lambda s: s.trainer_id)]
                    # distinct partner ids
                    trainers_for_off = list({t.id for t in sess_trainers if t})
                    # fallback to academy_trainer_ids if none
                    if not trainers_for_off and off.academy_trainer_ids:
                        trainers_for_off = [t.id for t in off.academy_trainer_ids]
                # If no offering/trainer found, skip this line
                if not trainers_for_off:
                    continue
                weight = 1.0 / max(1, len(trainers_for_off))
                for tid in trainers_for_off:
                    containers[tid].add(partner_id)
                    weights[tid] += weight
                    # name: use partner name
                    if not names.get(tid):
                        names[tid] = Partner.browse(tid).name or str(tid)

        else:
            # unknown entity
            return []

        # Build results: we prefer to use **unique student counts** (len of sets).
        results = []
        for key, students in containers.items():
            unique_count = len(students)
            # If we used fractional weighting and it differs, prefer integer unique_count for reporting.
            results.append({
                'key': key,
                'name': names.get(key, str(key)),
                'count': unique_count,
                'student_ids': list(students),
                # return numeric weight sum if available (mostly for location/trainer fractional)
                'weight_sum': float(weights.get(key, 0.0)),
            })

        # Sort by unique student count descending, tie-breaker by weight_sum desc
        results = sorted(results, key=lambda r: (r['count'], r.get('weight_sum', 0.0)), reverse=True)

        # Keep top 5
        top = results[:5]

        out = []
        for idx, item in enumerate(top, start=1):
            student_ids = item['student_ids'] or []
            rec = {
                'rank': idx,
                'id': item['key'] if not isinstance(item['key'], str) else 0,  # for locations (strings) id=0
                'name': item['name'],
                'value': int(item['count']),
                'student_ids': student_ids,
                'domain': [('id', 'in', student_ids)] if student_ids else [('id', 'in', [])],
            }
            # If it's a trainer or academy and key is an id, include it
            if entity in ('academy_id', 'trainer') and item['key']:
                rec['id'] = item['key']

            out.append(rec)

        return out
    
