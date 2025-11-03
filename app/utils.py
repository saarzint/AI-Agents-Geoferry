"""
This file contains the utility functions for the routes
like visa report, html report, and visa changes detection.
"""

def _generate_visa_report(visa_data: dict, citizenship: str, destination: str) -> dict:
	"""Generate user-facing visa checklist from structured data."""
	
	# Extract data with safe defaults
	documents = visa_data.get("documents", [])
	process_steps = visa_data.get("process_steps", [])
	fees = visa_data.get("fees", {})
	timelines = visa_data.get("timelines", {})
	interview = visa_data.get("interview", {})
	post_graduation = visa_data.get("post_graduation", [])
	
	# Create checklist items
	checklist_items = []
	
	# Documents checklist
	if documents:
		checklist_items.append({
			"category": "Required Documents",
			"items": [
				{
					"item": doc,
					"status": "pending",
					"priority": "high" if any(keyword in doc.lower() for keyword in ["passport", "financial", "medical"]) else "medium"
				}
				for doc in documents
			]
		})
	
	# Process steps checklist
	if process_steps:
		checklist_items.append({
			"category": "Application Process",
			"items": [
				{
					"item": step,
					"status": "pending",
					"priority": "high"
				}
				for step in process_steps
			]
		})
	
	# Special conditions detection
	special_conditions = []
	if any("financial" in str(fees).lower() or "bank" in str(fees).lower() for fees in [fees]):
		special_conditions.append("Financial proof required")
	if any("medical" in str(doc).lower() for doc in documents):
		special_conditions.append("Medical examination required")
	if interview and str(interview).lower() in ["true", "required", "mandatory"]:
		special_conditions.append("Interview required")
	
	report = {
		"title": f"Student Visa Checklist: {citizenship} → {destination}",
		"visa_type": visa_data.get("visa_type", "Student Visa"),
		"last_updated": visa_data.get("last_updated"),
		"source_url": visa_data.get("source_url"),
		"checklist": checklist_items,
		"special_conditions": special_conditions,
		"timeline": timelines,
		"fees": fees,
		"post_graduation_options": post_graduation,
		"disclaimer": "This information is for guidance only and not legal advice. Please verify all requirements with official sources.",
		"notes": visa_data.get("notes", [])
	}
	
	return report


def _generate_html_report(report: dict) -> str:
	"""Generate HTML version of visa report."""
	
	html = f"""
	<!DOCTYPE html>
	<html>
	<head>
		<title>{report['title']}</title>
		<style>
			body {{ font-family: Arial, sans-serif; margin: 20px; }}
			.header {{ background-color: #f0f8ff; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
			.checklist {{ margin: 20px 0; }}
			.category {{ font-weight: bold; font-size: 18px; margin: 15px 0 10px 0; color: #2c3e50; }}
			.item {{ margin: 8px 0; padding: 10px; border-left: 4px solid #3498db; background-color: #f8f9fa; }}
			.priority-high {{ border-left-color: #e74c3c; }}
			.priority-medium {{ border-left-color: #f39c12; }}
			.special {{ background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0; }}
			.disclaimer {{ background-color: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 5px; margin: 20px 0; font-style: italic; }}
			.meta {{ color: #6c757d; font-size: 14px; }}
		</style>
	</head>
	<body>
		<div class="header">
			<h1>{report['title']}</h1>
			<p class="meta">Visa Type: {report['visa_type']}</p>
			<p class="meta">Last Updated: {report['last_updated']}</p>
			<p class="meta">Source: <a href="{report['source_url']}" target="_blank">Official Source</a></p>
		</div>
	"""
	
	# Special conditions
	if report['special_conditions']:
		html += '<div class="special"><h3>⚠️ Special Conditions</h3><ul>'
		for condition in report['special_conditions']:
			html += f'<li>{condition}</li>'
		html += '</ul></div>'
	
	# Checklist
	for category in report['checklist']:
		html += f'<div class="checklist">'
		html += f'<div class="category">{category["category"]}</div>'
		for item in category['items']:
			priority_class = f"priority-{item['priority']}"
			html += f'<div class="item {priority_class}">'
			html += f'<input type="checkbox"> {item["item"]}'
			html += '</div>'
		html += '</div>'
	
	# Timeline and fees
	if report['timeline']:
		html += f'<div class="category">Processing Timeline</div><p>{report["timeline"]}</p>'
	
	if report['fees']:
		html += f'<div class="category">Application Fees</div><p>{report["fees"]}</p>'
	
	# Post-graduation options
	if report['post_graduation_options']:
		html += '<div class="category">Post-Graduation Work Options</div><ul>'
		for option in report['post_graduation_options']:
			html += f'<li>{option}</li>'
		html += '</ul>'
	
	# Notes
	if report['notes']:
		html += '<div class="category">Notes for Review</div><ul>'
		for note in report['notes']:
			html += f'<li>{note}</li>'
		html += '</ul>'
	
	# Disclaimer
	html += f'<div class="disclaimer"><strong>Disclaimer:</strong> {report["disclaimer"]}</div>'
	
	html += '</body></html>'
	return html


def _detect_visa_changes(supabase, citizenship: str, destination: str, user_profile_id: int, new_data: dict) -> dict:
	"""Detect changes in visa requirements and return change summary."""
	
	# Get the most recent existing data
	existing_resp = supabase.table("visa_requirements").select("*") \
		.eq("citizenship_country", citizenship) \
		.eq("destination_country", destination) \
		.eq("user_profile_id", user_profile_id) \
		.order("last_updated", desc=True).limit(1).execute()
	
	if not existing_resp.data:
		# No existing data, this is new
		return {
			"has_changes": False,
			"is_new": True,
			"changes": [],
			"alert_needed": False
		}
	
	existing_data = existing_resp.data[0]
	changes = []
	
	# Compare key fields
	fields_to_compare = ["visa_type", "documents", "process_steps", "fees", "timelines", "interview", "post_graduation"]
	
	for field in fields_to_compare:
		old_value = existing_data.get(field)
		new_value = new_data.get(field)
		
		if old_value != new_value:
			changes.append({
				"field": field,
				"old_value": old_value,
				"new_value": new_value,
				"change_type": "updated" if old_value and new_value else ("added" if new_value else "removed")
			})
	
	# Determine if alert is needed
	alert_needed = len(changes) > 0
	
	return {
		"has_changes": len(changes) > 0,
		"is_new": False,
		"changes": changes,
		"alert_needed": alert_needed,
		"previous_version_id": existing_data.get("id")
	}
