from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
from tavily import TavilyClient
import os

class OpenAIWebSearchInput(BaseModel):
    """Input schema for OpenAIWebSearchTool."""
    query: str = Field(..., description="The search query to execute using web search")

class OpenAIWebSearchTool(BaseTool):
    name: str = "OpenAI Web Search Tool"
    description: str = (
        "AI-powered web search tool for real-time, up-to-date information. "
        "Searches the web for current university information, admission requirements, "
        "rankings, and other educational data from trusted sources. "
        "Uses Tavily search engine for comprehensive web search results."
    )
    args_schema: Type[BaseModel] = OpenAIWebSearchInput

    def _run(self, query: str) -> str:
        """Execute web search using Tavily API."""
        try:
            tavily_api_key = os.getenv("TAVILY_API_KEY")
            if not tavily_api_key:
                return "Error: TAVILY_API_KEY environment variable is required for web search"
            
            client = TavilyClient(api_key=tavily_api_key)
            
            # Perform the search with focus on educational domains
            search_response = client.search(
                query=query,
                search_depth="advanced",
                max_results=10,
                include_answer=True,
                include_domains=[
                    "usnews.com", "niche.com", "collegeboard.org", 
                    "princetonreview.com", "petersons.com", "studentaid.gov",
                    "ed.gov", "collegeconfidential.com"
                ],
                exclude_domains=["wikipedia.org", "facebook.com", "twitter.com", "linkedin.com", "reddit.com", "quora.com"]
            )
            
            # Format the results
            result_parts = []
            
            # Include answer if available (Tavily returns a dict, not an object)
            if isinstance(search_response, dict):
                answer = search_response.get('answer')
                if answer:
                    result_parts.append(f"Summary: {answer}")
                
                # Include search results
                results = search_response.get('results', [])
                if results:
                    result_parts.append("\nSearch Results:")
                    for idx, result in enumerate(results[:8], 1):  # Limit to top 8 results
                        title = result.get('title', 'No title')
                        url = result.get('url', 'No URL')
                        content = result.get('content', 'No content available')
                        
                        result_parts.append(f"\n{idx}. {title}")
                        result_parts.append(f"   URL: {url}")
                        # Limit content length to avoid token overflow
                        content_preview = content[:500] + "..." if len(content) > 500 else content
                        result_parts.append(f"   Content: {content_preview}")
                    
                    # Include sources
                    sources_list = []
                    for result in results:
                        title = result.get('title', 'Unknown')
                        url = result.get('url', '')
                        if url:
                            sources_list.append(f"{title}: {url}")
                    
                    if sources_list:
                        result_parts.append(f"\n\nSources:")
                        result_parts.extend(sources_list)
            else:
                # Fallback if response format is unexpected
                result_parts.append(f"Search completed for: {query}")
                result_parts.append(f"Response: {str(search_response)[:1000]}")
            
            if not result_parts:
                return f"No results found for query: {query}"
            
            return "\n".join(result_parts)
            
        except Exception as e:
            # Return a more informative error message
            error_msg = str(e)
            if "getaddrinfo failed" in error_msg or "11001" in error_msg:
                return f"Web search failed: Network/DNS error - {error_msg}. Please check your internet connection."
            elif "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                return f"Web search failed: Authentication error - {error_msg}. Please check your TAVILY_API_KEY is set correctly."
            return f"Web search failed: {error_msg}"

