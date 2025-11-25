from crewai.tools import BaseTool
from typing import Type, Dict, Any
from pydantic import BaseModel, Field
import urllib.robotparser
from urllib.parse import urljoin, urlparse
from tavily import TavilyClient
import os
import json
from datetime import datetime

class WebDataRetrievalInput(BaseModel):
    """Input schema for WebDataRetrievalTool."""
    university: str = Field(..., description="Name of the university to search for")
    program: str = Field(None, description="Name of the specific program to search for (e.g., 'Computer Science', 'MBA')")

class WebDataRetrievalTool(BaseTool):
    name: str = "Web Data Retrieval Tool"
    description: str = (
        "Tool to retrieve and scrape university information from official websites. "
        "Respects robots.txt and focuses on official university subdomains. "
        "Uses Tavily search for finding relevant pages."
    )
    args_schema: Type[BaseModel] = WebDataRetrievalInput

    def _check_robots_txt(self, url: str) -> bool:
        """Check if the URL is allowed by robots.txt"""
        try:
            rp = urllib.robotparser.RobotFileParser()
            parsed_url = urlparse(url)
            robots_url = urljoin(f"{parsed_url.scheme}://{parsed_url.netloc}", "/robots.txt")
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch("*", url)
        except Exception:
            # If there's any error checking robots.txt, assume it's allowed
            return True

    def _extract_official_domain(self, university_name: str) -> str:
        """Extract the most likely official domain for a university"""
        university_lower = university_name.lower().strip()
        
        # Extended mapping of well-known universities to their official domains
        university_mappings = {
            # United Kingdom examples / .ac domains
            'university of hull': 'hull.ac.uk',
            'university of oxford': 'ox.ac.uk',
            'oxford university': 'ox.ac.uk',
            'university of cambridge': 'cam.ac.uk',
            'imperial college london': 'imperial.ac.uk',
            'university college london': 'ucl.ac.uk',
            'london school of economics': 'lse.ac.uk',
            'lse': 'lse.ac.uk',
            'university of manchester': 'manchester.ac.uk',
            'king\'s college london': 'kcl.ac.uk',
            'kings college london': 'kcl.ac.uk',
            'university of edinburgh': 'ed.ac.uk',
            'university of glasgow': 'gla.ac.uk',
            'university of birmingham': 'bham.ac.uk',
            'university of bristol': 'bristol.ac.uk',
            'university of leeds': 'leeds.ac.uk',
            'durham university': 'dur.ac.uk',
            'warwick university': 'warwick.ac.uk',
            'university of warwick': 'warwick.ac.uk',
            
            # University of Southern California
            'usc': 'usc.edu',
            'university of southern california': 'usc.edu',
            'southern california': 'usc.edu',
            
            # Ivy League & Top Universities
            'harvard': 'harvard.edu',
            'harvard university': 'harvard.edu',
            'harvard college': 'harvard.edu',
            
            'stanford': 'stanford.edu',
            'stanford university': 'stanford.edu',
            
            'mit': 'mit.edu',
            'massachusetts institute of technology': 'mit.edu',
            'm.i.t.': 'mit.edu',
            
            'yale': 'yale.edu',
            'yale university': 'yale.edu',
            
            'princeton': 'princeton.edu',
            'princeton university': 'princeton.edu',
            
            'cornell': 'cornell.edu',
            'cornell university': 'cornell.edu',
            
            'columbia': 'columbia.edu',
            'columbia university': 'columbia.edu',
            
            'university of pennsylvania': 'upenn.edu',
            'upenn': 'upenn.edu',
            'penn': 'upenn.edu',
            
            'dartmouth': 'dartmouth.edu',
            'dartmouth college': 'dartmouth.edu',
            
            'brown': 'brown.edu',
            'brown university': 'brown.edu',
            
            # Other Top Universities
            'duke': 'duke.edu',
            'duke university': 'duke.edu',
            
            'university of chicago': 'uchicago.edu',
            'uchicago': 'uchicago.edu',
            
            'northwestern': 'northwestern.edu',
            'northwestern university': 'northwestern.edu',
            
            'johns hopkins': 'jhu.edu',
            'johns hopkins university': 'jhu.edu',
            
            'cal tech': 'caltech.edu',
            'caltech': 'caltech.edu',
            'california institute of technology': 'caltech.edu',
            
            'georgetown': 'georgetown.edu',
            'georgetown university': 'georgetown.edu',
            
            'university of michigan': 'umich.edu',
            'umich': 'umich.edu',
            
            'university of california berkeley': 'berkeley.edu',
            'uc berkeley': 'berkeley.edu',
            'berkeley': 'berkeley.edu',
            
            'ucla': 'ucla.edu',
            'university of california los angeles': 'ucla.edu',
            
            'nyu': 'nyu.edu',
            'new york university': 'nyu.edu',
            
            'boston university': 'bu.edu',
            'bu': 'bu.edu',
            
            # State Universities
            'university of texas at austin': 'utexas.edu',
            'utexas': 'utexas.edu',
            
            'penn state': 'psu.edu',
            'pennsylvania state university': 'psu.edu',
            
            'university of washington': 'washington.edu',
            'uw': 'washington.edu',
            
            'university of wisconsin': 'wisc.edu',
            
            'university of florida': 'ufl.edu',
            'uf': 'ufl.edu',
            
            'university of illinois': 'illinois.edu',
            'uiuc': 'illinois.edu',
        }
        
        # Check exact match first
        if university_lower in university_mappings:
            return university_mappings[university_lower]
        
        # Try to extract a domain pattern from the university name
        # Remove common words
        words_to_remove = ['university', 'college', 'institute', 'of', 'the', 'at', 'in', 'for']
        name_words = [w for w in university_lower.split() if w not in words_to_remove]
        
        if not name_words:
            name_words = university_lower.split()
        
        # Generate possible domains
        # Pattern 1: First letters (e.g., "Massachusetts Institute of Technology" -> "mit")
        acronym = ''.join([w[0] for w in name_words if len(w) > 0]).lower()
        if len(acronym) >= 2:
            domain_options = [f'{acronym}.edu']
            
            # Pattern 2: Shortened first word + later words (e.g., "University of Texas" -> "utexas")
            if len(name_words) > 1:
                first_short = name_words[0][:2] if len(name_words[0]) > 2 else name_words[0]
                domain_options.append(f'{first_short}{"".join(name_words[1:])}.edu')
            
            # Pattern 3: First significant word (e.g., "Duke University" -> "duke")
            if len(name_words) > 0:
                domain_options.append(f'{name_words[0]}.edu')
                if 'california' in name_words:
                    domain_options.append(f'{name_words[-1]}.edu')
            
            # Return the most common pattern (acronym or first significant word)
            return domain_options[0] if domain_options else 'university.edu'
        
        # Fallback: just use first word
        if name_words:
            return f'{name_words[0]}.edu'
        
        return 'university.edu'

    def _generate_domain_candidates(self, university_name: str) -> list[str]:
        """Generate possible official domains, including common .ac.* variations."""
        primary_domain = self._extract_official_domain(university_name)
        candidates = [primary_domain]
        
        university_lower = university_name.lower().strip()
        words_to_remove = ['university', 'college', 'institute', 'of', 'the', 'at', 'in', 'for']
        name_words = [w for w in university_lower.split() if w not in words_to_remove]
        if not name_words:
            name_words = [w for w in university_lower.split() if w]
        
        base_tokens = set()
        if name_words:
            base_tokens.add(''.join(name_words))
            base_tokens.add(name_words[-1])
            if len(name_words) > 1:
                base_tokens.add(''.join(name_words[:2]))
        else:
            base_tokens.add(university_lower.replace(' ', ''))
        
        ac_tlds = [
            'ac.uk', 'ac.in', 'ac.nz', 'ac.jp', 'ac.kr', 'ac.za',
            'ac.il', 'ac.ae', 'ac.sg', 'ac.cn', 'ac.th', 'ac.id',
            'ac.ke', 'ac.ug', 'ac.tz'
        ]
        
        for base in base_tokens:
            if not base:
                continue
            for tld in ac_tlds:
                candidates.append(f'{base}.{tld}')
        
        # Remove duplicates while preserving order
        seen = set()
        ordered_candidates = []
        for domain in candidates:
            if domain and domain not in seen:
                ordered_candidates.append(domain)
                seen.add(domain)
        
        return ordered_candidates

    def _domain_matches(self, url: str, domain: str) -> bool:
        """Check if URL belongs to provided domain or its subdomain."""
        if not url or not domain:
            return False
        parsed_url = urlparse(url)
        netloc = parsed_url.netloc.lower()
        domain = domain.lower()
        return netloc == domain or netloc.endswith(f'.{domain}')

    def _is_official_domain(self, url: str, university_name: str) -> bool:
        """Check if the URL belongs to an official university domain"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        domain_candidates = self._generate_domain_candidates(university_name)
        exact_match = any(domain == candidate for candidate in domain_candidates)
        subdomain_match = any(domain.endswith(f'.{candidate}') for candidate in domain_candidates)
        
        # Also check for .edu domains with university name in them
        is_edu_or_ac = '.edu' in domain or '.ac.' in domain
        
        # If it's an exact match or subdomain match, it's official
        if exact_match or subdomain_match:
            return True
        
        # Check if it's .edu with university reference
        university_lower = university_name.lower()
        name_parts = [p for p in university_lower.split() if p.isalpha() and len(p) > 3]
        
        # Check for university name components in domain
        domain_matches = any(part in domain for part in name_parts) or any(part[:3] in domain for part in name_parts if len(part) > 3)
        
        return is_edu_or_ac and domain_matches

    def _search_university_info(self, university: str, program: str = None) -> Dict[str, Any]:
        """Search for specific program admission information using Tavily"""
        try:
            tavily_api_key = os.getenv('TAVILY_API_KEY')
            if not tavily_api_key:
                raise ValueError("Tavily API key is required")

            client = TavilyClient(api_key=tavily_api_key)
            
            domain_candidates = self._generate_domain_candidates(university)
            current_year = datetime.now().year
            next_year = current_year + 1
            
            all_results = []
            selected_official_domain = None
            
            if program:
                broader_queries = [
                    f'"{university}" "{program}" application requirements deadlines {current_year}',
                    f'"{university}" "{program}" admission requirements deadlines',
                    f'"{university}" "{program}" application deadlines'
                ]
            else:
                broader_queries = [
                    f"{university} admission requirements {current_year}"
                ]
            
            for official_domain in domain_candidates:
                official_queries = []
                if program:
                    official_queries = [
                        f'site:{official_domain} {program} application requirements',
                        f'site:{official_domain} {program} admissions requirements deadlines',
                        f'site:{official_domain} {program} department admission how to apply',
                        f'site:{official_domain} {program} program admission application',
                        f'site:{official_domain} {program} application deadlines {current_year} {next_year}',
                        f'site:{official_domain} {program} admission deadlines apply',
                        f'site:{official_domain} {program} deadlines early decision regular decision',
                        f'site:{official_domain} department {program} admission',
                        f'site:{official_domain} {program} requirements apply',
                        f'site:{official_domain} {program} degree admission requirements'
                    ]
                else:
                    official_queries = [
                        f'site:{official_domain} admission requirements',
                        f'site:{official_domain} admission application deadlines {current_year}',
                        f'site:{official_domain} admission deadlines apply'
                    ]
                
                candidate_results = []
                print(f"[DEBUG] Searching official domain: {official_domain}")
                for query in official_queries:
                    try:
                        search_result = client.search(
                            query=query,
                            search_depth="advanced",
                            exclude_domains=["wikipedia.org", "facebook.com", "twitter.com", "linkedin.com", "reddit.com", "quora.com"]
                        )
                        results = search_result.get('results', [])
                        if results:
                            candidate_results.extend(results)
                            print(f"[DEBUG] Found {len(results)} results from official domain query: {query}")
                    except Exception as e:
                        print(f"[DEBUG] Query failed: {query}, error: {str(e)}")
                        continue
                
                if not candidate_results:
                    continue
                
                has_domain_match = any(self._domain_matches(res.get('url', ''), official_domain) for res in candidate_results)
                if has_domain_match:
                    all_results.extend(candidate_results)
                    selected_official_domain = official_domain
                    break
                else:
                    print(f"[DEBUG] Results for domain {official_domain} did not include matching URLs, trying next candidate")
            
            # STAGE 2: If no official results or insufficient results, try broader search
            if not all_results or len(all_results) < 2:
                print(f"[DEBUG] Searching broader web for {university}")
                for query in broader_queries:
                    try:
                        search_result = client.search(
                            query=query,
                            search_depth="advanced",
                            exclude_domains=["wikipedia.org", "facebook.com", "twitter.com", "linkedin.com", "reddit.com", "quora.com"]
                        )
                        results = search_result.get('results', [])
                        if results:
                            all_results.extend(results)
                            print(f"[DEBUG] Found {len(results)} results from broader query: {query}")
                    except Exception as e:
                        continue
            else:
                print(f"[DEBUG] Found sufficient results from official domain, skipping broader search")
            
            if not selected_official_domain:
                # Fall back to first candidate for scoring/diagnostics
                selected_official_domain = domain_candidates[0] if domain_candidates else None
            
            # Process and filter results from all searches - find the BEST single result
            best_result = None
            best_score = -1
            seen_urls = set()  # Avoid duplicates
            
            for result in all_results:
                url = result.get('url')
                if url in seen_urls:
                    continue
                
                # Check if it's an official domain
                is_official = self._is_official_domain(url, university)
                url_lower = url.lower()
                if not is_official and '.edu' not in url_lower and '.ac.' not in url_lower:
                    continue  # Skip if it's not an official domain
                
                # Check robots.txt
                if not self._check_robots_txt(url):
                    continue
                
                seen_urls.add(url)
                
                # Calculate relevance score
                score = 0
                content = result.get('content', '').lower()
                title = result.get('title', '').lower()
                current_year = datetime.now().year
                
                # CRITICAL: Prioritize official domain matches (highest priority)
                if selected_official_domain and selected_official_domain in url_lower:
                    score += 50  # Massive boost for exact official domain match
                    print(f"[DEBUG] Official domain match found: {url}")
                elif '.edu' in url_lower or '.ac.' in url_lower:
                    score += 10  # Good score for any .edu domain
                else:
                    score += 5   # Lower score for other domains
                
                # CRITICAL: Prioritize program-specific pages
                if program:
                    program_words = [word.lower() for word in program.split() if len(word) > 2]
                    program_lower = program.lower()
                    
                    # Major boost for program name in URL
                    if any(prog_word in url_lower for prog_word in program_words):
                        score += 15
                    if program_lower in url_lower:
                        score += 20  # Exact program match in URL
                    
                    # Program-specific keywords in URL (high priority for accurate results)
                    # CRITICAL: For APPLICATION REQUIREMENTS, prioritize admission/apply pages
                    # Catalog pages show ACADEMIC requirements, not APPLICATION requirements
                    priority_keywords = {
                        '/admissions/': 20,          # Admissions pages (HIGHEST for application requirements)
                        '/apply/': 18,               # Application pages (HIGHEST for application requirements)
                        '/deadlines/': 15,           # Deadline pages (critical for applications)
                        'application': 12,           # Application keyword
                        'how-to-apply': 10,          # How to apply pages
                        '/prospective-students/': 8, # Prospective student pages
                        '/requirements/': 8,         # Requirements pages
                        'admission': 8,              # Admission keyword
                        '/department/': 7,           # Department pages
                        'catalogue': 5,             # Catalog pages (lower priority)
                        'preview_program.php': 5,   # Catalog program pages (lower priority)
                        '/programs/': 5,            # Program listing pages
                        'curriculum': 5,            # Curriculum pages
                        'graduate': 3,              # Graduate programs (MS, PhD)
                        'masters': 3,               # Master's programs
                        'phd': 3,                   # PhD programs
                    }
                    for keyword, points in priority_keywords.items():
                        if keyword in url_lower:
                            score += points
                    
                    # Score for program-specific content
                    # Check for program name appearing multiple times (indicates detailed program info)
                    program_name_count = sum(1 for prog_word in program_words if prog_word in content)
                    if program_name_count > 0:
                        score += min(program_name_count * 2, 15)  # Up to 15 points for program name mentions
                    
                    # Check for APPLICATION-specific content (NOT catalog/academic content)
                    # Catalog pages show course requirements, not application requirements
                    application_indicators = [
                        'application deadline', 'deadline', 'apply by', 
                        'required documents', 'transcript', 'recommendation', 
                        'essay prompt', 'personal statement', 'application fee',
                        'common app', 'coalition app', 'early decision', 'early action',
                        'test score', 'sat', 'act', 'how to apply'
                    ]
                    app_indicator_count = sum(1 for indicator in application_indicators if indicator in content.lower())
                    if app_indicator_count > 0:
                        score += min(app_indicator_count * 3, 15)  # Up to 15 points for application-specific content
                        print(f"[DEBUG] Application-specific content detected (score+{min(app_indicator_count * 3, 15)})")
                    
                    # Catalog indicators are LOWER priority for application requirements agent
                    catalog_indicators = ['units:', 'units', 'course requirements', 'credit hours', 
                                        'prerequisite', 'core courses', 'degree requirements']
                    catalog_count = sum(1 for indicator in catalog_indicators if indicator in content.lower())
                    if catalog_count > 0:
                        score += min(catalog_count, 2)  # Only 2 points max for catalog-style content
                        print(f"[DEBUG] Catalog-style content detected (score+{min(catalog_count, 2)})")
                    
                    # Title relevance
                    if any(prog_word in title for prog_word in program_words):
                        score += 5
                    
                    # Title contains program name strongly
                    if program_lower in title:
                        score += 10  # Strong title match
                
                # CRITICAL: Prioritize current and next year data
                year_keywords = [
                    str(current_year),
                    str(current_year + 1),
                    str(current_year + 2),
                    f'{current_year}-{current_year + 1}',
                ]
                for year_kw in year_keywords:
                    if year_kw in content or year_kw in title:
                        score += 10  # Strong boost for current/next year data
                        break
                
                # Flag if data appears outdated (past years)
                # BUT: Don't penalize catalog URLs with year IDs (catoid) - those are catalog editions
                is_catalog_url = 'preview_program' in url_lower or 'catalogue' in url_lower
                if not is_catalog_url:
                    for past_year in [str(current_year - 1), str(current_year - 2), str(current_year - 3)]:
                        if past_year in url_lower and current_year not in content:
                            score -= 20  # Penalty for old data
                            print(f"[DEBUG] Outdated content detected (year: {past_year}), penalty applied")
                
                # Application-related content scoring
                app_keywords = [
                    'application', 'admission', 'deadline', 'requirement',
                    'apply', 'fee', 'essay', 'transcript', 'recommendation',
                    'portfolio', 'interview', 'test score', 'sat', 'act', 'gpa'
                ]
                app_keyword_count = sum(1 for kw in app_keywords if kw in content)
                score += min(app_keyword_count, 8)  # Cap at 8 points
                
                # Department/program specific indicators
                department_indicators = ['department', 'program', 'major', 'degree', 'college', 'school']
                dept_count = sum(1 for ind in department_indicators if ind in url_lower)
                score += min(dept_count, 5)
                
                # Bonus for comprehensive content (more likely to have all requirements)
                content_length = len(content)
                if content_length > 2000:
                    score += 3  # Substantial content
                elif content_length > 1000:
                    score += 1  # Decent content
                
                # Penalty for very short content (likely not a complete requirements page)
                if content_length < 200:
                    score -= 5
                
                # CRITICAL: Penalty for catalog pages when searching for APPLICATION requirements
                # Catalog pages have program name but NO application information
                if 'catalogue' in url_lower or 'preview_program' in url_lower:
                    # Check if it has application info (deadlines, required docs, etc.)
                    has_app_info = any(indicator in content.lower()[:2000] for indicator in 
                                     ['application deadline', 'deadline', 'how to apply', 
                                      'required documents', 'essay', 'transcript', 'application fee'])
                    if not has_app_info:
                        score -= 20  # Strong penalty: catalog pages don't have application requirements
                        print(f"[DEBUG] Catalog page detected without application info, penalty applied")
                
                # Moderate penalty for pages with neither program name NOR application info
                has_app_keywords = any(kw in content.lower()[:2000] for kw in 
                                     ['application deadline', 'deadline', 'how to apply', 
                                      'required documents', 'essay', 'transcript'])
                if program and program_lower not in content.lower()[:1000] and not has_app_keywords:
                    score -= 10
                    print(f"[DEBUG] Generic page with no specific program or application info")
                
                # DEBUG: Print score for each result
                print(f"[DEBUG] URL: {url[:80]}... | Score: {score}")
                
                # If this is the best result so far, save it
                if score > best_score:
                    best_score = score
                    best_result = {
                        'title': result.get('title'),
                        'content': result.get('content'),
                        'source_url': url,
                        'retrieved_at': datetime.utcnow().isoformat(),
                        'relevance_score': score,
                        'official_domain_priority': official_domain in url_lower
                    }
            
            # Return only the best single result
            if best_result:
                filtered_results = [best_result]
            else:
                filtered_results = []
            
            return {
                'university': university,
                'program': program,
                'search_type': 'program' if program else 'university',
                'results': filtered_results
            }
            
        except Exception as e:
            return {
                'error': f"Error searching university information: {str(e)}",
                'university': university,
                'program': program,
                'search_type': 'program' if program else 'university',
                'results': []
            }

    def _run(self, university: str, program: str = None) -> Dict[str, Any]:
        """Execute web scraping for university application requirements."""
        if not university:
            return {"error": "University name is required"}
            
        result = self._search_university_info(
            university=university,
            program=program
        )
        
        # If there was an error, return it directly
        if 'error' in result:
            return result
            
        # If no results were found
        if not result['results']:
            return {
                'university': university,
                'program': program,
                'error': 'No results found from official university sources',
                'source_urls': []
            }
        
        # Return only the best single result for Application Data Extraction Tool
        if result['results']:
            best_item = result['results'][0]  # Only the best result
            return {
                'university': result['university'],
                'program': result['program'],
                'content': best_item['content'],
                'university_name': university,
                'program_name': program,
                'source_url': best_item['source_url'],
                'retrieved_at': best_item['retrieved_at'],
                'relevance_score': best_item.get('relevance_score', 0),
                'fetched_at': datetime.utcnow().isoformat(),
                'is_ambiguous': False
            }
        else:
            return {
                'university': university,
                'program': program,
                'error': 'No relevant official university sources found',
                'source_url': None,
                'fetched_at': datetime.utcnow().isoformat()
            }