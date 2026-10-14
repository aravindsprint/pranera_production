# Copyright (c) 2026, Pranera Services & Solutions
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class RollInspection(Document):

	def validate(self):
		from pranera_production.api.inspection import compute_roll_inspection
		compute_roll_inspection(self)

	def on_update(self):
		from pranera_production.api.inspection import after_roll_inspection_saved
		after_roll_inspection_saved(self)

	def on_trash(self):
		from pranera_production.api.inspection import after_roll_inspection_deleted
		after_roll_inspection_deleted(self)
