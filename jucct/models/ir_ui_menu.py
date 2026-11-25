from odoo import api, models

# Standard menus hidden from everybody except system administrators.
# Missing XML-ids (they differ between Community/Enterprise and between versions) are skipped.
HIDDEN_MENU_XMLIDS = [
    'mail.menu_root_discuss',
    'calendar.mail_menu_calendar',
    'contacts.menu_contacts',
    'crm.crm_menu_root',
    'sale.sale_menu_root',
    'spreadsheet_dashboard.spreadsheet_dashboard_menu_root',
    'account.menu_finance',
    'event.event_main_menu',
    'purchase.menu_purchase_root',
    'utm.menu_link_tracker_root',
    'base.menu_apps',
    'base.menu_administration',
]


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _jucct_restrict_menus(self):
        admin_group = self.env.ref('base.group_system')
        # res.groups relation field was renamed groups_id -> group_ids in Odoo 19
        field = 'group_ids' if 'group_ids' in self._fields else 'groups_id'
        for xmlid in HIDDEN_MENU_XMLIDS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu and menu._name == 'ir.ui.menu':
                menu.sudo().write({field: [(6, 0, admin_group.ids)]})
