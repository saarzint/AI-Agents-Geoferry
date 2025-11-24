from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
from openai import OpenAI
import os

class OpenAIWebSearchInput(BaseModel):
    """Input schema for OpenAIWebSearchTool."""
    query: str = Field(..., description="The search query to execute using OpenAI's web search")

class OpenAIWebSearchTool(BaseTool):
    name: str = "OpenAI Web Search Tool"
    description: str = (
        "AI-powered web search tool using OpenAI's built-in web search capability. "
        "Searches the web for real-time, up-to-date information. "
        "Use this tool to find current university information, admission requirements, "
        "rankings, and other educational data from trusted sources."
    )
    args_schema: Type[BaseModel] = OpenAIWebSearchInput

    def _run(self, query: str) -> str:
        """Execute web search using OpenAI's responses API with web_search tool."""
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return "Error: OPENAI_API_KEY environment variable is required"
            
            client = OpenAI(api_key=api_key)
            response = client.responses.create(
                model="gpt-5.1",
                tools=[{"type": "web_search"}],
                input=query
            )
            
            # Extract the search results
            if hasattr(response, 'output_text'):
                result = response.output_text
            elif hasattr(response, 'content'):
                result = str(response.content)
            else:
                result = str(response)
            
            # Include sources if available
            if hasattr(response, 'sources') and response.sources:
                sources_list = []
                for source in response.sources:
                    if isinstance(source, dict):
                        title = source.get('title', 'Unknown')
                        url = source.get('url', '')
                        sources_list.append(f"{title}: {url}")
                    else:
                        sources_list.append(str(source))
                if sources_list:
                    result += f"\n\nSources:\n" + "\n".join(sources_list)
            
            return result
        except Exception as e:
            return f"OpenAI web search failed: {str(e)}"

