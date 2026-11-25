{
    'name': 'Educational Center - Audit Log',
    'version': '20.0.1.0.0',
    'summary': 'Audit-log rules for the Educational Center module (needs OCA auditlog for 20.0)',
    'category': 'Education',
    'author': 'Raid Company Odoo Team',
    'license': 'LGPL-3',
    'depends': ['jucct', 'auditlog'],
    'data': ['data/auditlog_rule.xml'],
    'installable': True,
}
