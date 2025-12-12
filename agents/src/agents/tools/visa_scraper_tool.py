from __future__ import annotations

from typing import Type, Optional, List, Dict, Any
from datetime import datetime

import re
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from crewai.tools import BaseTool


class VisaScraperInput(BaseModel):
    """Input schema for VisaScraperTool."""
    url: str = Field(..., description="Official visa information page URL (gov/embassy/official site only)")
    user_agent: Optional[str] = Field(
        None,
        description="Optional User-Agent header to send with the request."
    )
    timeout_seconds: int = Field(20, description="HTTP request timeout in seconds")
    fields: Optional[List[str]] = Field(
        None,
        description="Optional list of fields to extract: visa_type, required_documents, application_process, processing_time, application_fees, interview_required, post_graduation_options"
    )


class VisaScraperTool(BaseTool):
    name: str = "Visa Scraper Tool"
    description: str = (
        "Scrape official visa pages (gov/embassy/authoritative) to extract student visa details. "
        "Use only when Tavily results lack structured data. Returns a JSON string with extracted fields."
    )
    args_schema: Type[BaseModel] = VisaScraperInput

    def _run(
        self,
        url: str,
        user_agent: Optional[str] = None,
        timeout_seconds: int = 20,
        fields: Optional[List[str]] = None,
        **_: Any,
    ) -> str:
        """Execute scraping and return a JSON-like string representation."""
        try:
            headers = {"User-Agent": user_agent or self._default_user_agent()}
            response = requests.get(url, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
        except Exception as e:
            return f"Error fetching URL: {e}"

        soup = BeautifulSoup(response.text, "lxml")
        text = self._extract_visible_text(soup)

        # Extract data and track what's missing/ambiguous
        notes = []
        visa_type = self._extract_visa_type(soup, text)
        if not visa_type:
            notes.append("visa_type: Could not identify specific visa type")
        
        required_documents = self._extract_list(soup, text, ["document", "documentation", "required documents", "what you need"])
        if not required_documents:
            notes.append("required_documents: No document list found")
        
        application_process = self._extract_list(soup, text, ["how to apply", "application process", "steps", "process"])
        if not application_process:
            notes.append("application_process: No step-by-step process found")
        
        processing_time = self._extract_processing_time(text)
        if not processing_time:
            notes.append("processing_time: No processing time information found")
        
        application_fees = self._extract_fees(text)
        if not application_fees:
            notes.append("application_fees: No fee information found")
        
        interview_required = self._extract_interview_required(text)
        if interview_required is None:
            notes.append("interview_required: Interview requirement unclear")
        
        post_graduation_options = self._extract_list(soup, text, ["post-study work", "post graduation", "opt", "psw", "post-study", "work after study"])
        if not post_graduation_options:
            notes.append("post_graduation_options: No post-graduation work options found")

        extracted: Dict[str, Any] = {
            "visa_type": visa_type,
            "required_documents": required_documents,
            "application_process": application_process,
            "processing_time": processing_time,
            "application_fees": application_fees,
            "interview_required": interview_required,
            "post_graduation_options": post_graduation_options,
            "disclaimer": "This information is for guidance only and not legal advice.",
            "source_url": url,
            "fetched_at": datetime.utcnow().isoformat(),
            "last_updated": datetime.utcnow().isoformat(),
            "notes": notes,
        }

        # If a subset of fields is requested, filter down
        if fields:
            filtered: Dict[str, Any] = {k: extracted.get(k) for k in fields if k in extracted}
            # Always include source and timestamps
            for meta_key in ("source_url", "fetched_at", "last_updated", "disclaimer"):
                filtered[meta_key] = extracted[meta_key]
            return self._to_json_like_string(filtered)

        return self._to_json_like_string(extracted)

    # --------------------------- Helpers --------------------------- #
    def _default_user_agent(self) -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    def _extract_visible_text(self, soup: BeautifulSoup) -> str:
        # Remove script/style
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(x.strip() for x in soup.stripped_strings)
        # Normalize whitespace
        return re.sub(r"\s+", " ", text)

    def _extract_visa_type(self, soup: BeautifulSoup, text: str) -> Optional[str]:
        # Try headline cues
        for h in soup.find_all(["h1", "h2", "h3"]):
            title = (h.get_text(" ", strip=True) or "").strip()
            if title:
                if re.search(r"(student\s+visa|f-1|tier\s*4|subclass\s*500|study\s+visa)", title, re.I):
                    return title
        # Fallback simple match in text
        m = re.search(r"(F-1\s+Student\s+Visa|Tier\s*4|Subclass\s*500|Student\s+Visa)", text, re.I)
        return m.group(1) if m else None

    def _extract_list(self, soup: BeautifulSoup, text: str, keywords: List[str]) -> List[str]:
        # Look for sections headed by keywords, then collect nearby list items
        items: List[str] = []
        pattern = re.compile("|".join(re.escape(k) for k in keywords), re.I)
        candidate_sections = []

        for header in soup.find_all(["h2", "h3", "h4", "strong"]):
            header_text = header.get_text(" ", strip=True) or ""
            if pattern.search(header_text):
                # capture following list items
                ul = header.find_next(["ul", "ol"])
                if ul:
                    for li in ul.find_all("li"):
                        item = (li.get_text(" ", strip=True) or "").strip()
                        if item:
                            items.append(item)
                candidate_sections.append(header)

        # Fallback: pick list items globally if keywords exist in page text
        if not items and pattern.search(text):
            for li in soup.find_all("li"):
                val = (li.get_text(" ", strip=True) or "").strip()
                if val:
                    items.append(val)

        # Deduplicate but keep order
        seen = set()
        deduped: List[str] = []
        for it in items:
            if it.lower() in seen:
                continue
            seen.add(it.lower())
            deduped.append(it)
        return deduped[:25]

    def _extract_processing_time(self, text: str) -> Optional[str]:
        # Look for patterns like "processing time", "processed within X weeks"
        m = re.search(r"processing time[:\s]+([\w\s\-–]+?)(?:\. |$)", text, re.I)
        if m:
            return m.group(1).strip()
        m2 = re.search(r"(\d+\s*[-–]?\s*\d*\s*(day|week|month|business day)s?)", text, re.I)
        return m2.group(0).strip() if m2 else None

    def _extract_fees(self, text: str) -> Optional[str]:
        # Capture currency/fee patterns
        m = re.search(r"(fee|application fee)[:\s\$€£]*([\$€£]?\s?\d+[\d,\.]*)(?:\s*(USD|EUR|GBP))?", text, re.I)
        return m.group(0).strip() if m else None

    def _extract_interview_required(self, text: str) -> Optional[bool]:
        if re.search(r"interview (required|mandatory)", text, re.I):
            return True
        if re.search(r"interview (not required|waived|optional)", text, re.I):
            return False
        return None

    def _to_json_like_string(self, data: Dict[str, Any]) -> str:
        # Minimal JSON-like formatting; agents consuming this will parse JSON
        import json
        return json.dumps(data, ensure_ascii=False)


