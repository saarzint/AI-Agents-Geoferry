from crewai.tools import BaseTool
from typing import Type, Dict, Any, Optional, List
from pydantic import BaseModel, Field
from crewai.knowledge.source.json_knowledge_source import JSONKnowledgeSource
import sys
import os
import json

# Add the app directory to the Python path for supabase_client if needed
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'app'))


class ScholarshipKnowledgeInput(BaseModel):
    """Input schema for ScholarshipKnowledgeTool."""
    query: str = Field(..., description="Search query for scholarships (e.g., 'computer science scholarships', 'merit-based', 'need-based financial aid')")
    limit: int = Field(5, description="Maximum number of scholarships to return")


class ScholarshipKnowledgeTool(BaseTool):
    name: str = "Scholarship Knowledge Tool"
    description: str = (
        "Search scholarship information using mock scholarship database with semantic search capabilities. "
        "This tool can find scholarships based on major, category (Merit-Based, Need-Based, etc.), "
        "demographics, and other criteria. It uses intelligent matching to provide relevant scholarship "
        "opportunities when web search is unavailable or returns no results."
    )
    args_schema: Type[BaseModel] = ScholarshipKnowledgeInput
    
    def __init__(self, **data):
        super().__init__(**data)
        # Store knowledge initialization status
        self._knowledge_initialized = False
        self._knowledge_file_path = None
        self._scholarships_data = None
        
        # Initialize the knowledge source
        self._initialize_knowledge()
    
    def _initialize_knowledge(self):
        """Initialize the scholarship knowledge source."""
        try:
            # For CrewAI Knowledge, files should be relative to the knowledge directory
            # The file path should be relative to the knowledge directory root
            knowledge_file = "scholarships.json"
            
            # Store the absolute path for simulation
            self._knowledge_file_path = self._get_knowledge_file_path()
            
            if self._knowledge_file_path and os.path.exists(self._knowledge_file_path):
                # Load scholarship data
                with open(self._knowledge_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._scholarships_data = data.get('scholarships', [])
                
                self._knowledge_initialized = True
                print(f"Scholarship Knowledge Tool initialized with {len(self._scholarships_data)} scholarships")
            else:
                print(f"Warning: Scholarship knowledge file not found at expected path: {self._knowledge_file_path}")
                self._knowledge_initialized = False
        
        except Exception as e:
            print(f"Error initializing Scholarship Knowledge Tool: {e}")
            self._knowledge_initialized = False
    
    def _get_knowledge_file_path(self):
        """Get the absolute path to the scholarships.json knowledge file."""
        try:
            # Get the directory of this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            
            knowledge_dir = os.path.join(current_dir, '..', '..', '..', 'knowledge')
            knowledge_file = os.path.join(knowledge_dir, 'scholarships.json')
            
            # Normalize the path
            knowledge_file = os.path.normpath(knowledge_file)
            
            return knowledge_file if os.path.exists(knowledge_file) else None
        
        except Exception as e:
            print(f"Error determining knowledge file path: {e}")
            return None
    
    def _semantic_search(self, query: str, scholarships: List[Dict], limit: int = 5) -> List[Dict]:
        """
        Perform semantic search on scholarships based on query.
        This is a simplified version - in a full implementation, this would use
        vector embeddings and similarity search.
        """
        query_lower = query.lower()
        scored_scholarships = []
        
        for scholarship in scholarships:
            score = 0
            
            # Search in name
            if any(term in scholarship.get('name', '').lower() for term in query_lower.split()):
                score += 3
            
            # Search in category
            if any(term in scholarship.get('category', '').lower() for term in query_lower.split()):
                score += 2
            
            # Search in eligibility_summary
            if any(term in scholarship.get('eligibility_summary', '').lower() for term in query_lower.split()):
                score += 2
            
            # Search in description
            if any(term in scholarship.get('description', '').lower() for term in query_lower.split()):
                score += 1
            
            # Search in provider
            if any(term in scholarship.get('provider', '').lower() for term in query_lower.split()):
                score += 1
            
            # Category-specific matching
            category_keywords = {
                'merit': ['merit-based', 'academic', 'gpa', 'excellence'],
                'need': ['need-based', 'financial', 'income', 'aid'],
                'major': ['major-specific', 'engineering', 'computer science', 'business', 'healthcare'],
                'demographic': ['demographic-specific', 'women', 'minority', 'first-generation'],
                'essay': ['essay', 'writing', 'creativity']
            }
            
            for category, keywords in category_keywords.items():
                if category in query_lower:
                    if any(keyword in scholarship.get('category', '').lower() or 
                           keyword in scholarship.get('eligibility_summary', '').lower() or
                           keyword in scholarship.get('description', '').lower()
                           for keyword in keywords):
                        score += 2
            
            # Major-specific matching
            major_keywords = {
                'computer science': ['computer science', 'software engineering', 'information technology', 'tech'],
                'engineering': ['engineering', 'mechanical', 'civil', 'electrical'],
                'business': ['business', 'economics', 'finance', 'marketing', 'management'],
                'healthcare': ['pre-med', 'nursing', 'public health', 'pharmacy', 'medical'],
                'environmental': ['environmental', 'sustainability', 'ecology', 'green']
            }
            
            for major, keywords in major_keywords.items():
                if any(term in query_lower for term in major.split()):
                    if any(keyword in scholarship.get('eligibility_summary', '').lower() or
                           keyword in scholarship.get('description', '').lower()
                           for keyword in keywords):
                        score += 3
            
            if score > 0:
                scored_scholarships.append((scholarship, score))
        
        # Sort by score (highest first) and return top results
        scored_scholarships.sort(key=lambda x: x[1], reverse=True)
        return [scholarship for scholarship, score in scored_scholarships[:limit]]
    
    def _run(self, query: str, limit: int = 5) -> str:
        """
        Search for scholarships using the knowledge base.
        
        Args:
            query: Search query string
            limit: Maximum number of scholarships to return
            
        Returns:
            JSON string containing matched scholarships
        """
        
        if not self._knowledge_initialized:
            return json.dumps({
                "error": "Scholarship knowledge base not initialized",
                "scholarships_found": 0,
                "scholarships": []
            })
        
        try:
            # Perform semantic search
            matched_scholarships = self._semantic_search(query, self._scholarships_data, limit)
            
            # Format results for consistency with web search results
            formatted_scholarships = []
            for scholarship in matched_scholarships:
                formatted_scholarship = {
                    "name": scholarship.get("name", ""),
                    "provider": scholarship.get("provider", ""),
                    "category": scholarship.get("category", ""),
                    "award_amount": scholarship.get("award_amount", ""),
                    "deadline": scholarship.get("deadline", ""),
                    "renewable_flag": scholarship.get("renewable_flag", False),
                    "description": scholarship.get("description", ""),
                    "eligibility_summary": scholarship.get("eligibility_summary", ""),
                    "source_url": scholarship.get("source_url", ""),
                    "source_type": "knowledge_base"
                }
                formatted_scholarships.append(formatted_scholarship)
            
            result = {
                "scholarships_found": len(formatted_scholarships),
                "scholarships": formatted_scholarships,
                "search_source": "knowledge_base",
                "query": query
            }
            
            return json.dumps(result, indent=2)
        
        except Exception as e:
            return json.dumps({
                "error": f"Error searching scholarship knowledge base: {str(e)}",
                "scholarships_found": 0,
                "scholarships": []
            })