import re

import frappe

BASE = "/assets/pranera_production/production_app/"


def get_context(context):
	"""Inject the built entry JS / CSS file names.

	Vite builds a content-hashed entry (index-<hash>.js) and CSS, so a new
	deploy gets new URLs and browsers never run a stale bundle. The names are
	read from the built index.html.

	Do NOT add a ?v= query to the entry script: the lazy page chunks import
	the entry by its plain URL, and a different URL makes the browser run a
	second copy of the app (the page then stays on Home after navigating).
	"""
	context.no_cache = 1
	context.entry_js = BASE + "index.js"
	context.entry_css = []
	try:
		html = open(frappe.get_app_path("pranera_production", "public", "production_app", "index.html")).read()
	except OSError:
		return
	js = re.search(r'<script[^>]+type="module"[^>]+src="([^"]+)"', html)
	if js:
		context.entry_js = js.group(1)
	context.entry_css = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
