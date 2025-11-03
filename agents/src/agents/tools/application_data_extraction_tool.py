from crewai.tools import BaseTool
from typing import Type, Dict, Any, Optional
from pydantic import BaseModel, Field
import json
import os
from datetime import datetime
from openai import OpenAI
import re


class ApplicationDataExtractionInput(BaseModel):
    """Input schema for ApplicationDataExtractionTool."""
    content: str = Field(..., description="Raw content from university website to extract structured data from")
    university_name: str = Field(..., description="Name of the university")
    program_name: str = Field(..., description="Name of the program")


class ApplicationDataExtractionTool(BaseTool):
    name: str = "Application Data Extraction Tool"
    description: str = (
        "Extracts structured application requirement data from university website content "
        "using OpenAI model. Handles missing or ambiguous data safely."
    )
    args_schema: Type[BaseModel] = ApplicationDataExtractionInput
    client: Optional[OpenAI] = None

    def __init__(self):
        super().__init__()
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # --------------------------- Core Extraction --------------------------- #
    def _extract_structured_data(self, content: str, university_name: str, program_name: str) -> Dict[str, Any]:
        """Call OpenAI model and safely parse structured output."""
        schema_example = {
            "application_platform": "string",
            "deadlines": {
                "early_decision": None,
                "early_action": None,
                "regular_decision": None,
                "priority": None,
                "rolling": False
            },
            "required_documents": [{"name": "string", "required": True, "details": None}],
            "essay_prompts": [{"type": "string", "prompt": "string", "word_limit": None}],
            "portfolio": {"required": False, "details": None},
            "interview": {"required": False, "policy": "string"},
            "fees": {
                "amount": None,
                "currency": "USD",
                "waiver_available": False,
                "waiver_details": None
            },
            "test_policy": {"type": "string", "details": None},
            "is_ambiguous": False,
            "ambiguity_details": None
        }
        
        prompt = f"""
Extract detailed application requirements for **{university_name}**'s **{program_name}** program
from the following website content. Return ONLY a valid JSON object (no markdown, no text outside braces).
Follow this schema exactly:

{json.dumps(schema_example, indent=2)}

Rules:
- Use null for missing values, don't invent data.
- PRESERVE date formats exactly as shown on the website (e.g., "December 1, 2025", "April 15, 2026")
- Do NOT convert dates to YYYY-MM-DD format - keep original website format
- For rolling admissions, set "rolling": true.
- Default currency: "USD" for US universities.
- Mark "is_ambiguous" true if any key info is unclear and explain in "ambiguity_details".
- PRIORITIZE program-specific requirements over general university requirements.
- If content contains both general and program-specific info, focus on the program-specific details.

CRITICAL DEADLINE EXTRACTION GUIDELINES:
- Look for deadline text patterns like: "Priority Deadline: December 1, 2025", "Regular Deadline: April 15, 2026", "Final Deadline: July 10, 2026"
- Extract ALL deadline types mentioned (Priority, Early Decision, Early Action, Regular Decision, Scholarship Deadline, Final Deadline)
- PRESERVE the original date format from the website
- For rolling admissions, look for phrases like "rolling basis" or "rolling admissions"
- If multiple deadlines are listed, map them correctly: Priority → priority, Regular → regular_decision, Scholarship → priority, Final → regular_decision
- Example: "Priority Deadline: December 1, 2025" → priority field should contain "December 1, 2025"
- Example: "Regular Deadline: April 15, 2026" → regular_decision field should contain "April 15, 2026"

Content:
{content}
        """.strip()

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",  # Using gpt-4o for better extraction accuracy
                messages=[
                    {"role": "system", "content": "You are a precise data extraction assistant. You specialize in extracting application deadlines, required documents, and admission requirements from university websites. Always output valid JSON only, following the schema exactly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=2000  # Increase token limit for comprehensive extraction
            )

            raw_output = response.choices[0].message.content.strip()

            # Clean output for safety (remove markdown fences or extra text)
            cleaned = re.sub(r"^```(json)?|```$", "", raw_output.strip(), flags=re.MULTILINE).strip()
            cleaned = cleaned.split("```")[0].strip()  # remove stray fences if any

            # Ensure it starts with '{' and ends with '}'
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("No valid JSON object found in response")
            json_text = cleaned[start:end]

            extracted_data = json.loads(json_text)

            # Add metadata
            extracted_data.update({
                "extracted_at": datetime.utcnow().isoformat(),
                "university_name": university_name,
                "program_name": program_name
            })
            return extracted_data

        except Exception as e:
            return {
                "error": f"Extraction failed: {str(e)}",
                "is_ambiguous": True,
                "ambiguity_details": "Model output not parseable as JSON",
                "university_name": university_name,
                "program_name": program_name,
                "extracted_at": datetime.utcnow().isoformat()
            }

    # --------------------------- CrewAI Tool Entry --------------------------- #
    def _run(self, **kwargs) -> str:
        # Handle both old format (structured_results) and new format (single result)
        if 'structured_results' in kwargs:
            # Old format - take the first (and only) result
            structured_results = kwargs.get("structured_results", [])
            if not structured_results:
                return json.dumps({"error": "No structured results provided"})

            item = structured_results[0]
            content = item.get("content")
            university_name = item.get("university_name")
            program_name = item.get("program_name")
            source_url = item.get("source_url")
        else:
            # New format - direct single result
            content = kwargs.get("content")
            university_name = kwargs.get("university_name")
            program_name = kwargs.get("program_name")
            source_url = kwargs.get("source_url")

        if not all([content, university_name, program_name]):
            return json.dumps({"error": "content, university_name, and program_name are required"})

        result = self._extract_structured_data(content, university_name, program_name)

        # Add source_url to the result if available
        if source_url:
            result["source_url"] = source_url

        # Return as JSON
        try:
            return json.dumps(result, ensure_ascii=False)
        except Exception:
            return json.dumps({"error": "Failed to serialize extraction result"})