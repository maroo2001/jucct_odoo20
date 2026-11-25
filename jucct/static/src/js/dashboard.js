
/** @odoo-module **/

import { Component, onWillStart, onMounted, proxy, signal } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const { DateTime } = luxon;
import { _t } from "@web/core/l10n/translation";
class EducationalDashboard extends Component {
    static template = "jucct.Dashboard";

    setup() {
        this.chartColors = {
                    // Main color and its variations
                    primary: '#539273',
                    primaryLight: '#6BAF8A',
                    primaryDark: '#3A7555',
                    
                    // Complementary colors
                    secondary: '#FF7B54',  // Coral - complements green well
                    accent: '#4A90E2',     // Blue - provides good contrast
                    highlight: '#FFB74D',  // Amber - for highlights
                    
                    // Neutral colors
                    neutral: '#95A5A6',
                    light: '#ECF0F1',
                    
                    // Additional colors for multiple datasets
                    color1: '#539273',     // Your main green
                    color2: '#4A90E2',     // Blue
                    color3: '#FF7B54',     // Coral
                    color4: '#9B59B6',     // Purple
                    color5: '#F39C12',     // Orange
                    color6: '#1ABC9C',     // Teal
                    color7: '#E74C3C',     // Red
                    color8: '#34495E',     // Dark blue/gray
                    
                    // Pastel versions for lighter charts
                    pastelGreen: '#D4EFDF',
                    pastelBlue: '#D6EAF8',
                    pastelCoral: '#FFE0D6',
                    pastelPurple: '#E8DAEF',
                    pastelAmber: '#FFECB3'
                };
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            academic_overview: {},
            student_overview: {},
            financial_overview: {},
            academies_overview: {},
            academies: [],
            programs: [],
            trainers: [],
            locations: [],
            time_range: 'ytd',
            date_range: {
                start: DateTime.local().startOf('year').toISODate(),
                end: DateTime.local().toISODate(),
            },
            academy_id: null,
            program_id: null,
            trainer_id: null,
            location: null,
            activeTab: 'financial',
        });
        this.paidUnpaidChartRef = signal.ref();
        this.topAcademiesChartRef = signal.ref();
        this.trendsChartRef = signal.ref();
        this.financialRevenueChartRef = signal.ref();
        this.revenueSettlementsChartRef = signal.ref();
        this.academyRevenueChartRef = signal.ref();
        this.academySettlementsChartRef = signal.ref();
        this.academyCoursesChartRef = signal.ref();
        this.trainerCoursesChartRef = signal.ref();
        this.locationCoursesChartRef = signal.ref();
        this.setTab = (tab) => {
            this.state.activeTab = tab;
            // ensure charts initialize after DOM update
            Promise.resolve().then(() => this.renderCharts());
        };

        onWillStart(async () => {
            if (typeof Chart === "undefined") {
                await loadJS("/web/static/lib/Chart/Chart.js");
            }
            await this.fetchAcademies();
            await this.fetchPrograms();
            await this.fetchTrainers();
            await this.fetchLocations();
            await this.fetchData();
        });
        onMounted(() => {
            this.renderCharts();
            
            // FIX: Remove the code that creates duplicate date inputs
            // Only setup event listeners for existing elements
            
            const rangeEl = document.getElementById('time_range');
            const startInput = document.getElementById('date_start');
            const endInput = document.getElementById('date_end');

            // Handle time range changes
            if (rangeEl) {
                rangeEl.addEventListener('change', (e) => {
                    this.state.time_range = e.target.value;
                    const today = DateTime.local();
                    let start = this.state.date_range.start;
                    let end = this.state.date_range.end;
                    switch (this.state.time_range) {
                        case 'ytd':
                            start = today.startOf('year').toISODate();
                            end = today.toISODate();
                            break;
                        case '7d':
                            start = today.minus({ days: 7 }).toISODate();
                            end = today.toISODate();
                            break;
                        case '30d':
                            start = today.minus({ days: 30 }).toISODate();
                            end = today.toISODate();
                            break;
                        case '60d':
                            start = today.minus({ days: 60 }).toISODate();
                            end = today.toISODate();
                            break;
                        case '90d':
                            start = today.minus({ days: 90 }).toISODate();
                            end = today.toISODate();
                            break;
                        case '180d':
                            start = today.minus({ days: 180 }).toISODate();
                            end = today.toISODate();
                            break;
                        case '3y':
                            start = today.minus({ years: 3 }).toISODate();
                            end = today.toISODate();
                            break;
                        case 'custom':
                        default:
                            // keep existing dates
                            break;
                    }
                    this.state.date_range.start = start;
                    this.state.date_range.end = end;
                    this.fetchData();
                });
            }

            // Only add event listeners if the inputs exist (they will when time_range is 'custom')
            if (startInput) {
                startInput.addEventListener('change', () => {
                    this.state.date_range.start = startInput.value;
                    this.state.time_range = 'custom';
                    this.fetchData();
                });
            }
            
            if (endInput) {
                endInput.addEventListener('change', () => {
                    this.state.date_range.end = endInput.value;
                    this.state.time_range = 'custom';
                    this.fetchData();
                });
            }

            const academyEl = document.getElementById('academy');
            if (academyEl) {
                academyEl.addEventListener('change', (e) => {
                    this.state.academy_id = e.target.value || null;
                    this.fetchData();
                });
            }
            const programEl = document.getElementById('program');
            if (programEl) {
                programEl.addEventListener('change', (e) => {
                    this.state.program_id = e.target.value || null;
                    this.fetchData();
                });
            }
            const trainerEl = document.getElementById('trainer');
            if (trainerEl) {
                trainerEl.addEventListener('change', (e) => {
                    this.state.trainer_id = e.target.value || null;
                    this.fetchData();
                });
            }
            const locationEl = document.getElementById('location');
            if (locationEl) {
                locationEl.addEventListener('change', (e) => {
                    this.state.location = e.target.value || null;
                    this.fetchData();
                });
            }
        });
    }
    async fetchAcademies() {
        this.state.academies = await this.orm.searchRead("res.partner", [['edu_type', '=', 'academy']], ['name']);
    }

    async fetchPrograms() {
        this.state.programs = await this.orm.searchRead("product.template", [['is_program', '=', true],['program_type', 'in', ['diploma','course']]], ['name']);
    }

    async fetchTrainers() {
        this.state.trainers = await this.orm.searchRead("res.partner", [['is_trainer', '=', true]], ['name']);
    }

   async fetchLocations() {
    const progs = await this.orm.searchRead(
        "product.template",
        [['is_program', '=', true], ['venue', '!=', false]],
        ['venue']
    );

    const fields = await this.orm.call(
        "product.template",
        "fields_get",
        [["venue"]]
    );
    const venueSelection = new Map(fields.venue.selection);

    const uniq = Array.from(new Set(progs.map(p => p.venue)))
        .filter(Boolean)
        .map(v => ({
            value: v,                 // backend value
            label: venueSelection.get(v), // frontend label
        }));

    this.state.locations = uniq;
}
    async fetchData() {
        const data = await this.orm.call("educational.dashboard", "get_dashboard_data", [], {
            start_date: this.state.date_range.start,
            end_date: this.state.date_range.end,
            academy_id: this.state.academy_id,
            program_id: this.state.program_id,
            trainer_id: this.state.trainer_id,
            location: this.state.location,
        });
        this.state.academic_overview = data.academic_overview;
        this.state.student_overview = data.student_overview;
        this.state.financial_overview = data.financial_overview;
        this.state.academies_overview = data.academies_overview;
        this.renderCharts();
    }

        renderCharts() {
        // Destroy existing charts
        const charts = [
            'paidUnpaidChart', 'topAcademiesChart', 'trendsChart', 
            'financialRevenueChart', 'revenueSettlementsChart', 
            'academyRevenueChart', 'academySettlementsChart',
            'academyCoursesChart', 'trainerCoursesChart', 'locationCoursesChart'
        ];
        
        charts.forEach(chartName => {
            if (this[chartName]) {
                this[chartName].destroy();
                this[chartName] = null;
            }
        });

        // Render charts based on active tab
        this.renderPaidUnpaidChart();
        this.renderTopAcademiesChart();
        this.renderTrendsChart();
        this.renderFinancialCharts();
        this.renderAcademyCharts();
        
        // Render academic overview charts
        if (this.state.activeTab === 'academic') {
            this.renderAcademicCharts();
        }
    }

    // Add new method to render academic charts
    renderAcademicCharts() {
        this.renderAcademyCoursesChart();
        this.renderTrainerCoursesChart();
        this.renderLocationCoursesChart();
    }

    renderAcademyCoursesChart() {
        if (!this.academyCoursesChartRef || !this.academyCoursesChartRef()) {
            return;
        }
        
        const data = this.state.academic_overview.academy_courses || {};
        const labels = data.labels || [];
        const values = data.values || [];

        this.academyCoursesChart = new Chart(this.academyCoursesChartRef(), {
            type: "bar",
        data: {
            labels: labels,
            datasets: [{
                label: _t("per Academy"),
                data: values,
                backgroundColor: [
                    this.chartColors.primary,
                    this.chartColors.primaryLight,
                    this.chartColors.color3,
                    this.chartColors.color4,
                    this.chartColors.color5,
                    this.chartColors.color6,
                ],
                borderColor: [
                    this.chartColors.primaryDark,
                    this.chartColors.color2,
                    this.chartColors.color3,
                    this.chartColors.color4,
                    this.chartColors.color5,
                    this.chartColors.color6,
                ],
                borderWidth: 1,
            }],
        },
            options: {
                responsive: true,
                maintainAspectRatio: false,
            },
        });
    }

    renderTrainerCoursesChart() {
        if (!this.trainerCoursesChartRef || !this.trainerCoursesChartRef()) {
            return;
        }
        
        const data = this.state.academic_overview.trainer_courses || {};
        const labels = data.labels || [];
        const values = data.values || [];


        this.trainerCoursesChart = new Chart(this.trainerCoursesChartRef(), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: _t("programs per Trainer"),
                    data: values,
                    backgroundColor: this.chartColors.color6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
            },
        });
    }

    renderLocationCoursesChart() {
        if (!this.locationCoursesChartRef || !this.locationCoursesChartRef()) {
            return;
        }
        
        const data = this.state.academic_overview.location_courses || {};
        const labels = data.labels || [];
        const values = data.values || [];

        this.locationCoursesChart = new Chart(this.locationCoursesChartRef(), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: _t("programs per Location"),
                    data: values,
                    backgroundColor: this.chartColors.color6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
            },
        });
    }

renderTrendsChart() {
        // ensure DOM node exists and data present
        if (!this.trendsChartRef || !this.trendsChartRef()) {
            return;
        }
        const trends = (this.state && this.state.student_overview && this.state.student_overview.trends) || {};
        const labels = Array.isArray(trends.labels) ? trends.labels : [];
        const newRegs = Array.isArray(trends.new_registrations) ? trends.new_registrations : [];
        const withdrawn = Array.isArray(trends.withdrawn_students) ? trends.withdrawn_students : [];

        // nothing to render
        if (labels.length === 0 && newRegs.length === 0 && withdrawn.length === 0) {
            return;
        }

        if (this.trendsChart) {
            this.trendsChart.destroy();
            this.trendsChart = null;
        }

        this.trendsChart = new Chart(this.trendsChartRef(), {
            type: "line",
            data: {
                labels: labels,
 datasets: [
                {
                    label: _t("New Registrations"),
                    data: newRegs,
                    borderColor: this.chartColors.primary,
                    backgroundColor: this.chartColors.pastelGreen,
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4,
                },
                {
                    label: _t("Withdrawals"),
                    data: withdrawn,
                    borderColor: this.chartColors.color7,
                    backgroundColor: this.chartColors.pastelCoral,
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4,
                },
            ],
            },
            options: {responsive: true,
        maintainAspectRatio: false,},
        });
    }

    renderFinancialCharts() {
        // Revenue Chart
        if (this.financialRevenueChartRef && this.financialRevenueChartRef()) {
            const trends = (this.state && this.state.financial_overview && this.state.financial_overview.revenue_trends) || {};
            const labels = Array.isArray(trends.labels) ? trends.labels : [];
            const revenue = Array.isArray(trends.revenue) ? trends.revenue : [];

            if (labels.length > 0 && revenue.length > 0) {
                if (this.financialRevenueChart) {
                    this.financialRevenueChart.destroy();
                    this.financialRevenueChart = null;
                }

                this.financialRevenueChart = new Chart(this.financialRevenueChartRef(), {
                    type: "bar",
                    data: {
                        labels: labels,
                        datasets: [{
                            label: _t("Monthly Revenue"),
                            data: revenue,
                            backgroundColor: this.chartColors.color6,
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                    },
                });
            }
        }

        // Revenue vs Settlements Chart
        if (this.revenueSettlementsChartRef && this.revenueSettlementsChartRef()) {
            const trends = (this.state && this.state.financial_overview && this.state.financial_overview.revenue_trends) || {};
            const labels = Array.isArray(trends.labels) ? trends.labels : [];
            const revenue = Array.isArray(trends.revenue) ? trends.revenue : [];
            const settlements = Array.isArray(trends.settlements) ? trends.settlements : [];

            if (labels.length > 0 && revenue.length > 0 && settlements.length > 0) {
                if (this.revenueSettlementsChart) {
                    this.revenueSettlementsChart.destroy();
                    this.revenueSettlementsChart = null;
                }

                this.revenueSettlementsChart = new Chart(this.revenueSettlementsChartRef(), {
                    type: "line",
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: _t("Revenue"),
                                data: revenue,
                                borderColor: this.chartColors.primary,
                                fill: false,
                            },
                            {
                                label: _t("Settlements"),
                                data: settlements,
                                borderColor: this.chartColors.color6,
                                fill: false,
                            },
                        ],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                    },
                });
            }
        }
    }

    renderAcademyCharts() {
        // Academy Revenue Chart
        if (this.academyRevenueChartRef && this.academyRevenueChartRef()) {
            const top3 = (this.state && this.state.academies_overview && this.state.financial_overview.top_5_academies) || [];
            const labels = top3.map(a => a.name);
            const revenue = top3.map(a => a.value);

            if (labels.length > 0 && revenue.length > 0) {
                if (this.academyRevenueChart) {
                    this.academyRevenueChart.destroy();
                    this.academyRevenueChart = null;
                }

                this.academyRevenueChart = new Chart(this.academyRevenueChartRef(), {
                    type: "bar",
                    data: {
                        labels: labels,
                        datasets: [{
                            label:_t("Academy Revenue"),
                            data: revenue,
                            backgroundColor: [this.chartColors.primary,this.chartColors.color6, "#ffc107"],
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                    },
                });
            }
        }
    }

     renderPaidUnpaidChart() {
        // ensure DOM node exists
        if (!this.paidUnpaidChartRef || !this.paidUnpaidChartRef()) {
            return;
        }

        const fin = this.state && this.state.financial_overview ? this.state.financial_overview : {};
        const paid = typeof fin.paid_invoices === 'number' ? fin.paid_invoices : Number(fin.paid_invoices) || 0;
        const unpaid = typeof fin.unpaid_invoices === 'number' ? fin.unpaid_invoices : Number(fin.unpaid_invoices) || 0;

        if (this.paidUnpaidChart) {
            this.paidUnpaidChart.destroy();
            this.paidUnpaidChart = null;
        }

        this.paidUnpaidChart = new Chart(this.paidUnpaidChartRef(), {
            type: "doughnut",
             data: {
            labels: [_t("Paid"), _t("Unpaid")],
            datasets: [
                {
                    label: _t("Invoices"),
                    data: [paid, unpaid],
                            backgroundColor: [this.chartColors.primary,
                        this.chartColors.color6,],
                    borderColor: [
                        this.chartColors.primaryDark,
                    ],
                    borderWidth: 1,
                },
            ],
        },
            options: {
                responsive: true,
                maintainAspectRatio: false,
            
            },
        });
    }
   renderTopAcademiesChart() {
        // ensure DOM node exists
        if (!this.topAcademiesChartRef || !this.topAcademiesChartRef()) {
            return;
        }

        const top = (this.state.academies_overview && this.state.student_overview.top_5_academies) || [];
        const labels = top.map(a => (a && a.name) ? a.name : '—');
        const data = top.map(a => (a && typeof a.value === 'number') ? a.value : 0);
        const colors = [this.chartColors.primary,this.chartColors.color6, "#ffc107"];
        if (this.topAcademiesChart) {
            this.topAcademiesChart.destroy();
        }
        this.topAcademiesChart = new Chart(this.topAcademiesChartRef(), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: _t("students"),
                        data: data,
                        backgroundColor: labels.map((_, i) => colors[i] || colors[0]),
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
            },
        });
    }

    openRecord(model, id, context={}) {
        if (!model || !id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Open',
            res_model: model,
            res_id: Number(id),
            views: [[false, 'form']],
            context: context
        });
    }
    
     openRecordWithDomain(model, domains=[],context={}) {
        if (!model) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Open',
            res_model: model,
            views: [[false, 'list'], [false, 'form']],
            domain: domains,
            context: context
        });
    }

    async openDrillDown(statistic) {
        let action = false;
        const resolveXmlId = async (xmlid) => {
        try {
            return await this.orm.call('educational.dashboard', 'get_xmlid_res_id', [xmlid]);
        } catch (e) {
            return false;
        }
    };
        const invoiceReportId = await resolveXmlId('jucct.enrollment_invoice_report');
        const startDate = (this.state && this.state.date_range && this.state.date_range.start)
            ? this.state.date_range.start
            : DateTime.local().startOf('month').toISODate();
        const endDate = (this.state && this.state.date_range && this.state.date_range.end)
            ? this.state.date_range.end
            : DateTime.local().endOf('month').toISODate();
        const academyFilterFor = (fieldName) => this.state.academy_id ? [[fieldName, '=', Number(this.state.academy_id)]] : [];
        const programFilterFor = (fieldName) => this.state.program_id ? [[fieldName, '=', Number(this.state.program_id)]] : [];

        switch (statistic) {
            case 'total_active_programs':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Active Programs'),
                    res_model: 'product.template',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['status', '=', 'active'], ['is_program', '=', true]],
                    context: {'default_is_program': true, 'form_view_ref': 'jucct.educational_jucct_form_view'}
                };
                break;
            case 'total_active_courses':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Active Courses'),
                    res_model: 'product.template',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['status', '=', 'active'], ['program_type', '=', 'course']],
                    context: {'default_program_type': 'course','default_is_program': true, 'form_view_ref': 'jucct.educational_jucct_form_view'}
                };
                break;
            case 'total_active_diplomas':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Active Diplomas'),
                    res_model: 'product.template',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['status', '=', 'active'], ['program_type', '=', 'diploma']],
                    context: {'default_program_type': 'diploma','default_is_program': true, 'form_view_ref': 'jucct.educational_jucct_form_view'}
                };
                break;
                    case 'upcoming_sessions': {
                        const today = new Date();
                        const sevenDaysLater = new Date();
                        sevenDaysLater.setDate(today.getDate() + 7);

                        // Convert to Odoo-compatible date strings (YYYY-MM-DD)
                        const formatDate = d => d.toISOString().slice(0, 10);
                        const start = formatDate(today);
                        const end = formatDate(sevenDaysLater);

                        action = {
                            type: 'ir.actions.act_window',
                            name: _t('Upcoming Sessions'),
                            res_model: 'academy.session',
                            views: [[false, 'list'], [false, 'form']],
                            domain: [
                                ['session_date', '>=', start],
                                ['session_date', '<=', end],
                                ['status', '=', 'scheduled']
                            ],
                        };

                    }
                break;
            case 'total_students':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Students'),
                    res_model: 'res.partner',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['edu_type', '=', 'student']],
                    context: { form_view_ref: 'jucct.student_jucct_form_view', default_edu_type: 'student', default_invoice_template_pdf_report_id: invoiceReportId, list_view_ref: 'jucct.student_jucct_list_view'} 
                };
                break;
            case 'new_registrations':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('New Registrations'),
                    res_model: 'sale.order',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['is_enrolment', '=', true], ['create_date', '>=', startDate], ['create_date', '<=', endDate],
                    ...academyFilterFor('order_line.academy_id'),
                    ...programFilterFor('order_line.product_id.product_tmpl_id'),],           
                    context: {'form_view_ref': 'jucct.enrollment_jucct_form_view','default_type': 'sale','default_is_enrolment' : true,'list_view_ref': 'jucct.enrollment_jucct_list_view'  }
                };
                break;
            case 'withdrawn_students':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Withdrawn Students'),
                    res_model: 'sale.order',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['enrolment_status', '=', 'withdrawn'],
                    ...academyFilterFor('order_line.academy_id'),
                    ...programFilterFor('order_line.product_id.product_tmpl_id'),],
                    context: {'form_view_ref': 'jucct.enrollment_jucct_form_view','default_type': 'sale','default_is_enrolment' : true }

                };
                break;
            case _t('completed_programs'):
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Completed Programs'),
                    res_model: 'academy.program.offering',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['status', '=', 'expired'], ['end_date', '>=', startDate], ['end_date', '<=', endDate],
                    ...academyFilterFor('academy_id'),
                    ...programFilterFor('program_id'),],
                };
                break;
            case 'total_invoices':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Invoices'),
                    res_model: 'account.move',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['is_enrollment', '=', true],
                        ['invoice_date', '>=', startDate],
                        ['invoice_date', '<=', endDate],                        
                    ...academyFilterFor('invoice_line_ids.academy_id'),
                    ...programFilterFor('invoice_line_ids.product_id.product_tmpl_id'),],
                    context: {'create':false,'list_view_ref': 'jucct.view_move_list_inherit_program_fields'}
                };
                break;
            case 'paid_invoices':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Paid Invoices'),
                    res_model: 'account.move',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['is_enrollment', '=', true], ['payment_state', 'in', ['paid','partial','withdrawn']],
                        ['invoice_date', '>=', startDate],
                        ['invoice_date', '<=', endDate],
                    ...academyFilterFor('invoice_line_ids.academy_id'),
                    ...programFilterFor('invoice_line_ids.product_id.product_tmpl_id'),],
                    context: {'create':false,'list_view_ref': 'jucct.view_move_list_inherit_program_fields'}
                };
                break;
            case 'unpaid_invoices':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Unpaid Invoices'),
                    res_model: 'account.move',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['is_enrollment', '=', true], ['payment_state', '!=', 'paid'],
                        ['invoice_date', '>=', startDate],
                        ['invoice_date', '<=', endDate],
                    ...academyFilterFor('invoice_line_ids.academy_id'),
                    ...programFilterFor('invoice_line_ids.product_id.product_tmpl_id'),],
                    context: {'create':false,'list_view_ref': 'jucct.view_move_list_inherit_program_fields'}
                };
                break;
            case 'pending_settlements':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Pending Settlements'),
                    res_model: 'academy.financial.settlement',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['settlement_status', '=', 'draft']
                       ,['settlement_date', '>=', startDate],
                        ['settlement_date', '<=', endDate],
                        ...academyFilterFor('academy_id'),
                        ...programFilterFor('program_id'),]
                };
                break;
            case 'paid_settlements':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Pending Settlements'),
                    res_model: 'academy.financial.settlement',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['settlement_status', '=', 'paid']
                       ,['settlement_date', '>=', startDate],
                        ['settlement_date', '<=', endDate],
                        ['is_center_settlement', '=', false],
                        ...academyFilterFor('academy_id'),
                        ...programFilterFor('program_id'),]
                };
                break;
            case 'total_active_academies':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Active Academies'),
                    res_model: 'res.partner',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['edu_type', '=', 'academy'], ['contract_status', '=', 'active']],
                    context: {'form_view_ref': 'jucct.academy_jucct_form_view','list_view_ref': 'jucct.academy_jucct_list_view',  'default_company_type': 'company', 'default_edu_type': 'academy'},
                };
                break;
            case 'academies_with_pending_settlements':
                action = {
                    type: 'ir.actions.act_window',
                    name: _t('Academies with Pending Settlements'),
                    res_model: 'academy.financial.settlement',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['settlement_status', '=', 'draft'],
                        ['settlement_date', '>=', startDate],
                        ['settlement_date', '<=', endDate],
                        ...academyFilterFor('academy_id'),],
                };
                break;
        }
        if (action) {
            this.action.doAction(action);
        }
    }
}


registry.category("actions").add("jucct.educational_dashboard", EducationalDashboard);
