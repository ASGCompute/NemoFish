"""
Report Agent Service
ReACT-pattern simulation report generation using LangChain + Zep

Features:
1. Generate reports from simulation requirements and Zep graph data
2. Plan outline structure first, then generate section by section
3. Each section uses ReACT multi-round reasoning pattern
4. Support user chat with autonomous retrieval tool calls
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)

logger = get_logger('nemofish.report_agent')


class ReportLogger:
    """
    Report Agent detailed logger
    
    Generates agent_log.jsonl in report folder, logging every action step.
    Each line is a complete JSON object with timestamp, action type, and details.
    """
    
    def __init__(self, report_id: str):
        """
        Initialize logger
        
        Args:
            report_id: Report ID, determines log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Ensure log file directory exists"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """Get elapsed time from start (seconds)"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        Record a log entry
        
        Args:
            action: 动作类型，如 'start', 'tool_call', 'llm_response', 'section_complete' 等
            stage: 当前阶段，如 'planning', 'generating', 'completed'
            details: 详细内容字典，不截断
            section_title: 当前章节标题（可选）
            section_index: 当前章节索引（可选）
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # 追加写入 JSONL 文件
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Log report generation start"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": "报告生成任务开始"
            }
        )
    
    def log_planning_start(self):
        """记录Outline planning开始"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": "开始规划Report outline"}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """记录规划时获取的上下文信息"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": "获取模拟上下文信息",
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """记录Outline planning完成"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": "Outline planning complete",
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """记录Section generation开始"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": f"开始生成章节: {section_title}"}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """记录 ReACT 思考过程"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": f"ReACT 第{iteration}轮思考"
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """Log tool call"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": f"调用工具: {tool_name}"
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """Log tool call结果（完整内容，不截断)"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # 完整结果，不截断
                "result_length": len(result),
                "message": f"工具 {tool_name} 返回结果"
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """记录 LLM 响应（完整内容，不截断)"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # 完整响应，不截断
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": f"LLM 响应 (工具调用: {has_tool_calls}, 最终答案: {has_final_answer})"
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """Log section content生成完成（仅记录内容，不代表整sections完成)"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # 完整内容，不截断
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": f"章节 {section_title} 内容生成完成"
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        记录Section generation完成

        前端应监听此日志来判断一sections是否真正完成，并获取完整内容
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": f"章节 {section_title} 生成完成"
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """记录Report generation complete"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": "Report generation complete"
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """Log error"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": f"发生错误: {error_message}"
            }
        )


class ReportConsoleLogger:
    """
    Report Agent 控制台日志记录器
    
    将控制台风格的日志（INFO、WARNING等）写入报告文件夹中的 console_log.txt 文件。
    这些日志与 agent_log.jsonl 不同，是纯文本格式的控制台输出。
    """
    
    def __init__(self, report_id: str):
        """
        初始化控制台日志记录器
        
        Args:
            report_id: Report ID, determines log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """Ensure log file directory exists"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """设置文件处理器，将日志同时写入文件"""
        import logging
        
        # 创建文件处理器
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # 使用与控制台相同的简洁格式
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # 添加到 report_agent 相关的 logger
        loggers_to_attach = [
            'nemofish.report_agent',
            'nemofish.zep_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # 避免重复添加
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """关闭文件处理器并从 logger 中移除"""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'nemofish.report_agent',
                'nemofish.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """析构时确保关闭文件处理器"""
        self.close()


class ReportStatus(str, Enum):
    """报告状态"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """Report section"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """转换为Markdown格式"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """Report outline"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """Full report"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Prompt 模板常量
# ═══════════════════════════════════════════════════════════════

# ── 工具描述 ──

TOOL_DESC_INSIGHT_FORGE = """\
[Deep Insight Retrieval - Powerful retrieval tool]
This is our powerful retrieval function designed for deep analysis. It will:
1. Automatically decompose your question into multiple sub-questions
2. Retrieve information from the simulation graph across multiple dimensions
3. Integrate semantic search, entity analysis, and relationship chain tracking results
4. Return the most comprehensive and in-depth retrieval content

[Use Cases]
- Need deep analysis of a topic
- Need to understand multiple aspects of an event
- Need rich material to support report sections

[Returns]
- Relevant original facts (can be directly quoted)
- Core entity insights
- Relationship chain analysis"""

TOOL_DESC_PANORAMA_SEARCH = """\
[Broad Search - Get panoramic view]
This tool provides a complete overview of simulation results, especially suitable for understanding event evolution. It will:
1. Retrieve all related nodes and relationships
2. Distinguish between currently valid facts and historical/expired facts
3. Help you understand how public opinion evolved

[Use Cases]
- Need to understand the complete development trajectory of an event
- Need to compare opinion changes across different stages
- Need comprehensive entity and relationship information

[Returns]
- Currently valid facts (latest simulation results)
- Historical/expired facts (evolution records)
- All involved entities"""

TOOL_DESC_QUICK_SEARCH = """\
[Simple Search - Quick retrieval]
A lightweight quick retrieval tool suitable for simple, direct information queries.

[Use Cases]
- Need to quickly find specific information
- Need to verify a fact
- Simple information retrieval

[Returns]
- List of facts most relevant to the query"""

TOOL_DESC_INTERVIEW_AGENTS = """\
[Deep Interview - Real Agent Interview (Dual Platform)]
Calls the OASIS simulation environment's interview API to conduct real interviews with running simulation agents!
This is not LLM simulation - it calls the real interview interface to get original responses from simulation agents.
By default, interviews are conducted on both Twitter and Reddit platforms for more comprehensive perspectives.

Workflow:
1. Automatically reads persona files to understand all simulation agents
2. Intelligently selects agents most relevant to the interview topic (e.g., students, media, officials)
3. Automatically generates interview questions
4. Calls /api/simulation/interview/batch for real dual-platform interviews
5. Integrates all interview results for multi-perspective analysis

[Use Cases]
- Need different role perspectives on events (What do students think? What does media say? What's the official position?)
- Need to collect opinions and positions from multiple parties
- Need real responses from simulation agents (from the OASIS simulation environment)
- Want to make the report more vivid with "interview transcripts"

[Returns]
- Identity information of interviewed agents
- Interview responses from each agent on both Twitter and Reddit platforms
- Key quotes (can be directly cited)
- Interview summary and perspective comparison

[Important] Requires the OASIS simulation environment to be running!"""

# -- Outline planning prompt --

PLAN_SYSTEM_PROMPT = """\
You are a "Future Prediction Report" writing expert with a "God's-eye view" of the simulated world — you can observe every agent's behavior, statements, and interactions.

[Core Concept]
We built a simulated world and injected specific "simulation requirements" as variables. The evolution results of the simulated world serve as predictions of what may happen in the future. What you are observing is not "experimental data" but a "rehearsal of the future."

[Your Task]
Write a "Future Prediction Report" answering:
1. Under our specified conditions, what happened in the future?
2. How did different types of agents (populations) react and act?
3. What noteworthy future trends and risks does this simulation reveal?

[Report Positioning]
- ✅ This is a simulation-based future prediction report, revealing "if this happens, what would the future look like"
- ✅ Focus on prediction results: event trajectories, group reactions, emergent phenomena, potential risks
- ✅ Agent statements and actions in the simulation ARE predictions of future population behavior
- ❌ Not an analysis of current real-world conditions
- ❌ Not a generic public opinion overview

[Section Count Limits]
- Minimum 2 sections, maximum 5 sections
- No sub-sections needed, each section should contain complete content
- Content should be focused on core prediction findings
- Section structure is designed by you based on prediction results

Output the report outline in JSON format:
{
    "title": "Report title",
    "summary": "Report summary (one sentence summarizing core prediction findings)",
    "sections": [
        {
            "title": "Section title",
            "description": "Section content description"
        }
    ]
}

Note: The sections array must have at least 2 and at most 5 elements!"""

PLAN_USER_PROMPT_TEMPLATE = """\
[Prediction Scenario Setup]
Variable injected into the simulated world (simulation requirement): {simulation_requirement}

[Simulated World Scale]
- Number of entities in simulation: {total_nodes}
- Number of relationships generated: {total_edges}
- Entity type distribution: {entity_types}
- Active agent count: {total_entities}

[Sample of Future Facts Predicted by Simulation]
{related_facts_json}

Please examine this future rehearsal from a "God's-eye view":
1. Under our specified conditions, what state did the future present?
2. How did different populations (agents) react and act?
3. What noteworthy future trends does this simulation reveal?

Design the most appropriate report section structure based on prediction results.

[Reminder] Report sections: minimum 2, maximum 5, content should be focused on core prediction findings."""

# -- Section generation prompt --

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
You are a "Future Prediction Report" writing expert, currently writing a section of the report.

Report Title: {report_title}
Report Summary: {report_summary}
Prediction Scenario (simulation requirement): {simulation_requirement}

Current section to write: {section_title}

═══════════════════════════════════════════════════════════════
[Core Concept]
═══════════════════════════════════════════════════════════════

The simulated world is a rehearsal of the future. We injected specific conditions (simulation requirements)
into the simulated world. The behaviors and interactions of agents in the simulation are predictions of future population behavior.

Your task is to:
- Reveal what happened in the future under the specified conditions
- Predict how different populations (agents) reacted and acted
- Discover noteworthy future trends, risks, and opportunities

❌ Do NOT write an analysis of current real-world conditions
✅ Focus on "what will the future look like" — simulation results ARE the predicted future

═══════════════════════════════════════════════════════════════
[Most Important Rules - Must Follow]
═══════════════════════════════════════════════════════════════

1. [Must call tools to observe the simulated world]
   - You are observing a future rehearsal from a "God's-eye view"
   - All content must come from events and agent behaviors in the simulated world
   - Do NOT use your own knowledge to write report content
   - Each section must call tools at least 3 times (max 5) to observe the simulated world

2. [Must quote agents' original statements and actions]
   - Agent statements and behaviors are predictions of future population behavior
   - Use quote format to present these predictions, e.g.:
     > "A certain group would state: original content..."
   - These quotes are core evidence of simulation predictions

3. [Language consistency - all content must be in English]
   - Tool-returned content may contain mixed languages
   - The report must be written entirely in English
   - When quoting tool results in other languages, translate them to fluent English
   - Maintain original meaning while ensuring natural expression
   - This rule applies to both body text and quoted blocks (> format)

4. [Faithfully present prediction results]
   - Report content must reflect simulation results representing the future
   - Do not add information that doesn't exist in the simulation
   - If information is insufficient in some areas, state this honestly

═══════════════════════════════════════════════════════════════
[⚠️ Format Specifications - Extremely Important!]
═══════════════════════════════════════════════════════════════

[One section = minimum content unit]
- Each section is the smallest unit of the report
- ❌ Do NOT use any Markdown headings (#, ##, ###, #### etc.) within sections
- ❌ Do NOT add section title at the beginning of content
- ✅ Section title is automatically added by the system, you only write body text
- ✅ Use **bold**, paragraph breaks, quotes, lists to organize content, but no headings

[Correct Example]
```
This section analyzes the event's public opinion propagation trends. Through deep analysis of simulation data, we found...

**Initial Outbreak Phase**

Twitter served as the primary frontline for information dissemination:

> "Twitter contributed 68% of the initial volume..."

**Emotion Amplification Phase**

The Reddit platform further amplified the event's impact:

- Strong visual impact
- High emotional resonance
```

[Incorrect Example]
```
## Executive Summary          ← Wrong! Do not add any headings
### 1. Initial Phase          ← Wrong! Do not use ### for subsections
#### 1.1 Detailed Analysis    ← Wrong! Do not use #### for subdivision

This section analyzes...
```

═══════════════════════════════════════════════════════════════
[Available Retrieval Tools] (call 3-5 times per section)
═══════════════════════════════════════════════════════════════

{tools_description}

[Tool Usage Tips - Mix different tools, don't use just one]
- insight_forge: Deep insight analysis, auto-decomposes questions and retrieves facts/relationships across dimensions
- panorama_search: Wide-angle panoramic search, understand full picture, timeline, and evolution
- quick_search: Quick verification of specific information points
- interview_agents: Interview simulation agents, get first-person perspectives and real reactions from different roles

═══════════════════════════════════════════════════════════════
[Workflow]
═══════════════════════════════════════════════════════════════

Each response you can only do ONE of the following two things (not both):

Option A - Call a tool:
Output your thinking, then call a tool using this format:
<tool_call>
{{"name": "tool_name", "parameters": {{"param_name": "param_value"}}}}
</tool_call>
The system will execute the tool and return results to you. You cannot write tool results yourself.

Option B - Output final content:
When you have gathered enough information through tools, output section content starting with "Final Answer:"

⚠️ Strictly prohibited:
- Do NOT include both tool calls and Final Answer in one response
- Do NOT fabricate tool results (Observations), all tool results are injected by the system
- Each response can call at most one tool

═══════════════════════════════════════════════════════════════
[Section Content Requirements]
═══════════════════════════════════════════════════════════════

1. Content must be based on simulation data retrieved through tools
2. Extensively quote original text to demonstrate simulation results
3. Use Markdown format (but no headings):
   - Use **bold text** to mark key points (instead of sub-headings)
   - Use lists (- or 1.2.3.) to organize points
   - Use blank lines to separate paragraphs
   - ❌ Do NOT use #, ##, ###, #### or any heading syntax
4. [Quote format - must be standalone paragraph]
   Quotes must be independent paragraphs, with a blank line before and after:

   ✅ Correct format:
   ```
   The response was considered lacking in substance.

   > "The response pattern appeared rigid and slow in the rapidly changing social media environment."

   This assessment reflects widespread public dissatisfaction.
   ```

   ❌ Incorrect format:
   ```
   The response was considered lacking.> "The response pattern..." This assessment reflects...
   ```
5. Maintain logical coherence with other sections
6. [Avoid repetition] Carefully read completed sections below, do not repeat the same information
7. [Emphasis] Do NOT add any headings! Use **bold** instead of sub-headings"""

SECTION_USER_PROMPT_TEMPLATE = """\
Completed section content (read carefully to avoid repetition):
{previous_content}

═══════════════════════════════════════════════════════════════
[Current Task] Write section: {section_title}
═══════════════════════════════════════════════════════════════

[Important Reminders]
1. Carefully read the completed sections above to avoid repeating the same content!
2. You MUST call tools before starting to write to retrieve simulation data
3. Mix different tools, don't use just one type
4. Report content must come from retrieval results, do NOT use your own knowledge

[⚠️ Format Warning - Must Follow]
- ❌ Do NOT write any headings (#, ##, ###, #### are all forbidden)
- ❌ Do NOT write "{section_title}" as a heading
- ✅ Section title is automatically added by the system
- ✅ Write body text directly, use **bold** instead of sub-headings

Begin:
1. First think (Thought) about what information this section needs
2. Then call tools (Action) to retrieve simulation data
3. After collecting enough information, output Final Answer (pure body text, no headings)"""

# -- ReACT loop message templates --

REACT_OBSERVATION_TEMPLATE = """\
Observation (retrieval results):

═══ Tool {tool_name} returned ═══
{result}

═══════════════════════════════════════════════════════════════
Tools called: {tool_calls_count}/{max_tool_calls} (used: {used_tools_str}){unused_hint}
- If information is sufficient: output section content starting with "Final Answer:" (must quote the above text)
- If more information needed: call another tool to continue retrieval
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[Notice] You have only called tools {tool_calls_count} times, at least {min_tool_calls} required. "
    "Please call more tools to retrieve simulation data before outputting Final Answer. {unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "Currently only {tool_calls_count} tool calls made, at least {min_tool_calls} required. "
    "Please call tools to retrieve simulation data. {unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "Tool call limit reached ({tool_calls_count}/{max_tool_calls}), no more tools can be called. "
    'Please immediately output section content starting with "Final Answer:" based on information already gathered.'
)

REACT_UNUSED_TOOLS_HINT = "\n💡 You haven't used: {unused_list} yet, try different tools for multi-angle information"

REACT_FORCE_FINAL_MSG = "Tool call limit reached, please output Final Answer: and generate section content now."

# -- Chat prompt --

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
You are a concise, efficient simulation prediction assistant.

[Background]
Prediction scenario: {simulation_requirement}

[Generated Analysis Report]
{report_content}

[Rules]
1. Prioritize answering based on the report content above
2. Answer directly, avoid lengthy deliberation
3. Only call tools to retrieve more data when report content is insufficient
4. Answers should be concise, clear, and well-organized

[Available Tools] (use only when needed, max 1-2 calls)
{tools_description}

[Tool Call Format]
<tool_call>
{{"name": "tool_name", "parameters": {{"param_name": "param_value"}}}}
</tool_call>

[Response Style]
- Concise and direct, avoid lengthy exposition
- Use > format to quote key content
- Give conclusions first, then explain reasoning"""

CHAT_OBSERVATION_SUFFIX = "\n\nPlease answer the question concisely."


# ═══════════════════════════════════════════════════════════════
# ReportAgent Main Class
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - 模拟报告生成Agent

    采用ReACT（Reasoning + Acting）模式：
    1. 规划阶段：分析模拟需求，规划报告目录结构
    2. 生成阶段：逐Section generation内容，每章节可多次调用工具获取信息
    3. 反思阶段：检查内容完整性和准确性
    """
    
    # 最大工具调用次数（每sections）
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # 最大反思轮数
    MAX_REFLECTION_ROUNDS = 3
    
    # 对话中的最大工具调用次数
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        初始化Report Agent
        
        Args:
            graph_id: 图谱ID
            simulation_id: 模拟ID
            simulation_requirement: 模拟需求描述
            llm_client: LLM client（可选）
            zep_tools: Zep工具服务（可选）
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        
        # 工具定义
        self.tools = self._define_tools()
        
        # 日志记录器（在 generate_report 中初始化）
        self.report_logger: Optional[ReportLogger] = None
        # 控制台日志记录器（在 generate_report 中初始化）
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(f"ReportAgent 初始化完成: graph_id={graph_id}, simulation_id={simulation_id}")
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """定义可用工具"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "你想深入分析的问题或话题",
                    "report_context": "当前Report section的上下文（可选，有助于生成更精准的子问题)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "搜索查询，用于相关性排序",
                    "include_expired": "是否包含过期/历史内容（默认True)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "搜索查询字符串",
                    "limit": "返回结果数量（可选，默认10)"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "Interview topic或需求描述（如：'了解学生对宿舍甲醛事件的看法')",
                    "max_agents": "最多采访的Agent数量（可选，默认5，最大10)"
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        Execute tool call
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            report_context: 报告上下文（用于InsightForge）
            
        Returns:
            工具执行结果（文本格式）
        """
        logger.info(f"执行工具: {tool_name}, 参数: {parameters}")
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # 广度搜索 - 获取全貌
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # 简单搜索 - 快速检索
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                # 深度采访 - 调用真实的OASIS采访API获取模拟Agent的回答（双平台）
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()
            
            # ========== 向后兼容的旧工具（内部重定向到新工具） ==========
            
            elif tool_name == "search_graph":
                # 重定向到 quick_search
                logger.info("search_graph 已重定向到 quick_search")
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # 重定向到 insight_forge，因为它更强大
                logger.info("get_simulation_context 已重定向到 insight_forge")
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"未知工具: {tool_name}。请使用以下工具之一: insight_forge, panorama_search, quick_search"
                
        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, 错误: {str(e)}")
            return f"工具执行失败: {str(e)}"
    
    # 合法的工具名称集合，用于裸 JSON 兜底解析时校验
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        从LLM响应中解析工具调用

        支持的格式（按优先级）：
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. 裸 JSON（响应整体或单行就是一个工具调用 JSON）
        """
        tool_calls = []

        # 格式1: XML风格（标准格式）
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # 格式2: 兜底 - LLM 直接输出裸 JSON（没包 <tool_call> 标签）
        # 只在格式1未匹配时尝试，避免误匹配正文中的 JSON
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # 响应可能包含思考文字 + 裸 JSON，尝试提取最后一个 JSON 对象
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """校验解析出的 JSON 是否是合法的工具调用"""
        # 支持 {"name": ..., "parameters": ...} 和 {"tool": ..., "params": ...} 两种键名
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # 统一键名为 name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """生成工具描述文本"""
        desc_parts = ["可用工具："]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  参数: {params_desc}")
        return "\n".join(desc_parts)
    
    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        规划Report outline
        
        使用LLM分析模拟需求，规划报告的目录结构
        
        Args:
            progress_callback: 进度回调函数
            
        Returns:
            ReportOutline: Report outline
        """
        logger.info("开始规划Report outline...")
        
        if progress_callback:
            progress_callback("planning", 0, "正在分析模拟需求...")
        
        # 首先获取模拟上下文
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, "正在生成Report outline...")
        
        system_prompt = PLAN_SYSTEM_PROMPT
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, "正在解析大纲结构...")
            
            # 解析大纲
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=response.get("title", "模拟分析报告"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, "Outline planning complete")
            
            logger.info(f"Outline planning complete: {len(sections)} sections")
            return outline
            
        except Exception as e:
            logger.error(f"Outline planning failed: {str(e)}")
            # Return default outline (3 sections, as fallback)
            return ReportOutline(
                title="Future Prediction Report",
                summary="Future trends and risk analysis based on simulation predictions",
                sections=[
                    ReportSection(title="Prediction Scenarios and Key Findings"),
                    ReportSection(title="Population Behavior Prediction Analysis"),
                    ReportSection(title="Trend Outlook and Risk Indicators")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        Generate a single section using ReACT pattern.
        
        ReACT loop:
        1. Thought - analyze what information is needed
        2. Action - call tools to get information
        3. Observation - analyze tool results
        4. Repeat until enough info or max iterations
        5. Final Answer - generate section content
        
        Args:
            section: Section to generate
            outline: Complete outline
            previous_sections: Previous section contents (for coherence)
            progress_callback: Progress callback
            section_index: Section index (for logging)
            
        Returns:
            Section content (Markdown format)
        """
        logger.info(f"ReACT generating section: {section.title}")
        
        # Log section start
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )

        # Build user prompt - each completed section max 4000 chars
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # Each section max 4000 chars
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(This is the first section)"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ReACT loop
        tool_calls_count = 0
        max_iterations = 5  # Max iteration rounds
        min_tool_calls = 3  # Min tool calls required
        conflict_retries = 0  # Consecutive conflict count (tool call + Final Answer together)
        used_tools = set()  # Track used tool names
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Report context for InsightForge sub-question generation
        report_context = f"Section title: {section.title}\nSimulation requirement: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    f"Deep retrieval and writing ({tool_calls_count}/{self.MAX_TOOL_CALLS_PER_SECTION})"
                )
            
            # Call LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4096
            )

            # Check if LLM returned None (API error or empty content)
            if response is None:
                logger.warning(f"Section {section.title} iteration {iteration + 1}: LLM returned None")
                # If iterations remain, add message and retry
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(Response was empty)"})
                    messages.append({"role": "user", "content": "Please continue generating content."})
                    continue
                # Last iteration also returned None, break to forced completion
                break

            logger.debug(f"LLM response: {response[:200]}...")

            # Parse once, reuse results
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # -- Conflict handling: LLM output both tool call and Final Answer --
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    f"Section {section.title} round {iteration+1}: "
                    f"LLM output both tool call and Final Answer (conflict #{conflict_retries})"
                )

                if conflict_retries <= 2:
                    # First two times: discard response, ask LLM to re-respond
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Format Error] You included both a tool call and Final Answer in one response, which is not allowed.\n"
                            "Each response can only do one of the following:\n"
                            "- Call a tool (output a <tool_call> block, do NOT write Final Answer)\n"
                            "- Output final content (start with 'Final Answer:', do NOT include <tool_call>)\n"
                            "Please respond again, doing only one of these."
                        ),
                    })
                    continue
                else:
                    # Third time: fallback, truncate to first tool call, force execute
                    logger.warning(
                        f"Section {section.title}: {conflict_retries} consecutive conflicts, "
                        "falling back to truncated first tool call execution"
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # Log LLM response
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # -- Case 1: LLM output Final Answer --
            if has_final_answer:
                # Insufficient tool calls, reject and request more tools
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"(These tools haven't been used yet, try them: {', '.join(unused_tools)})" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # Normal completion
                final_answer = response.split("Final Answer:")[-1].strip()
                logger.info(f"章节 {section.title} 生成完成（工具调用: {tool_calls_count}次)")

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # -- Case 2: LLM attempted tool call --
            if has_tool_calls:
                # Tool quota exhausted -> explicitly inform, request Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # Execute only the first tool call
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(f"LLM attempted {len(tool_calls)} tool calls, executing only first: {call['name']}")

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # Build unused tools hint
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list=", ".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # -- Case 3: Neither tool call nor Final Answer --
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # Insufficient tool calls, recommend unused tools
                unused_tools = all_tools - used_tools
                unused_hint = f"(These tools haven't been used yet, try them: {', '.join(unused_tools)})" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Tool calls sufficient, LLM output content without "Final Answer:" prefix
            # Directly adopt this content as final answer
            logger.info(f"章节 {section.title} 未检测到 'Final Answer:' 前缀，直接采纳LLM输出作为最终内容（工具调用: {tool_calls_count}次)")
            final_answer = response.strip()

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # Max iterations reached, force content generation
        logger.warning(f"Section {section.title} reached max iterations, forcing generation")
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4096
        )

        # Check if LLM returned None during forced completion
        if response is None:
            logger.error(f"Section {section.title}: LLM returned None during forced completion, using default error")
            final_answer = f"（本Section generation失败：LLM 返回空响应，请稍后重试)"
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response
        
        # Log section content generation complete
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        Generate complete report (real-time section-by-section output)
        
        Each section is saved to folder immediately after generation, no need to wait for entire report.
        File structure:
        reports/{report_id}/
            meta.json       - Report metadata
            outline.json    - Report outline
            progress.json   - Generation progress
            section_01.md   - Section 1
            section_02.md   - Section 2
            ...
            full_report.md  - Full report
        
        Args:
            progress_callback: Progress callback function (stage, progress, message)
            report_id: Report ID (optional, auto-generated if not provided)
            
        Returns:
            Report: Full report
        """
        import uuid
        
        # Auto-generate report_id if not provided
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # Completed section titles (for progress tracking)
        completed_section_titles = []
        
        try:
            # Initialize: create report folder and save initial state
            ReportManager._ensure_report_folder(report_id)
            
            # Initialize logger (structured log agent_log.jsonl)
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # Initialize console logger (console_log.txt)
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, "Initializing report...",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # Phase 1: Plan outline
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, "开始规划Report outline...",
                completed_sections=[]
            )
            
            # Log planning start
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, "开始规划Report outline...")
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # Log planning complete
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # Save outline to file
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, f"Outline planning complete, {len(outline.sections)} sections",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(f"Outline saved to file: {report_id}/outline.json")
            
            # Phase 2: Generate sections (save per section)
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # Save content for context
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # Update progress
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    f"Generating section: {section.title} ({section_num}/{total_sections})",
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )
                
                if progress_callback:
                    progress_callback(
                        "generating", 
                        base_progress, 
                        f"Generating section: {section.title} ({section_num}/{total_sections})"
                    )
                
                # Generate main section content
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # Save section
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Log section complete
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(f"Section saved: {report_id}/section_{section_num:02d}.md")
                
                # Update progress
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    f"Section {section.title} completed",
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # 阶段3: 组装Full report
            if progress_callback:
                progress_callback("generating", 95, "正在组装Full report...")
            
            ReportManager.update_progress(
                report_id, "generating", 95, "正在组装Full report...",
                completed_sections=completed_section_titles
            )
            
            # 使用ReportManager组装Full report
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # Calculate total time
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # Log report complete
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # Save final report
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, "Report generation complete",
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, "Report generation complete")
            
            logger.info(f"Report generation complete: {report_id}")
            
            # Close console logger
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # Log error
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # Save failed state
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, f"Report generation failed: {str(e)}",
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # Ignore save failure errors
            
            # Close console logger
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Chat with Report Agent.
        
        The agent can autonomously call retrieval tools to answer questions.
        
        Args:
            message: User message
            chat_history: Chat history
            
        Returns:
            {
                "response": "Agent reply",
                "tool_calls": [list of tool calls],
                "sources": [information sources]
            }
        """
        logger.info(f"Report Agent chat: {message[:50]}...")
        
        chat_history = chat_history or []
        
        # Get generated report content
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # Limit report length to avoid excessive context
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [Report content truncated] ..."
        except Exception as e:
            logger.warning(f"Failed to get report content: {e}")
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "（No report available yet)",
            tools_description=self._get_tools_description(),
        )

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add chat history
        for h in chat_history[-10:]:  # Limit history length
            messages.append(h)
        
        # Add user message
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # ReACT loop（简化版）
        tool_calls_made = []
        max_iterations = 2  # Reduce iteration rounds
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # Parse tool calls
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # No tool calls, return response directly
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # Execute tool calls (limited count)
            tool_results = []
            for call in tool_calls[:1]:  # Max 1 tool call per round
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # Limit result length
                })
                tool_calls_made.append(call)
            
            # Add results to messages
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']} result]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # Max iterations reached, get final response
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # Clean response
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    报告管理器
    
    负责报告的持久化存储和检索
    
    文件结构（分章节输出）：
    reports/
      {report_id}/
        meta.json          - Report metadata和状态
        outline.json       - Report outline
        progress.json      - Generation progress
        section_01.md      - Section 1
        section_02.md      - Section 2
        ...
        full_report.md     - Full report
    """
    
    # Report storage directory
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """Ensure reports root directory exists"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """Get report folder path"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """Ensure report folder exists and return path"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """获取Report metadata文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """获取Full reportMarkdown文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """Get outline file path"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """Get progress file path"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """Get section Markdown file path"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Get Agent log file path"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """Get console log file path"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get console log content.
        
        These are console output logs during report generation (INFO, WARNING, etc.),
        different from structured logs in agent_log.jsonl.
        
        Args:
            report_id: Report ID
            from_line: Line to start reading from (for incremental retrieval, 0 = start)
            
        Returns:
            {
                "logs": [log lines list],
                "total_lines": total line count,
                "from_line": start line number,
                "has_more": whether more logs exist
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # Keep original log line, strip trailing newline
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Read to end
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        Get complete console log (all at once).
        
        Args:
            report_id: Report ID
            
        Returns:
            Log lines list
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get Agent log content.
        
        Args:
            report_id: Report ID
            from_line: Line to start reading from (for incremental retrieval, 0 = start)
            
        Returns:
            {
                "logs": [log entries list],
                "total_lines": total line count,
                "from_line": start line number,
                "has_more": whether more logs exist
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # Skip lines that fail to parse
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Read to end
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Get complete Agent log (all at once).
        
        Args:
            report_id: Report ID
            
        Returns:
            Log entries list
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        保存Report outline
        
        Called immediately after planning phase
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Outline saved: {report_id}")
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        Save a single section.

        Called immediately after each section is generated.

        Args:
            report_id: Report ID
            section_index: Section index (starting from 1)
            section: Section object

        Returns:
            Saved file path
        """
        cls._ensure_report_folder(report_id)

        # Build section Markdown content - clean possible duplicate titles
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # Save file
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"Section saved: {report_id}/{file_suffix}")
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        Clean section content.
        
        1. Remove duplicate Markdown heading lines matching section title
        2. Convert all ### and lower level headings to bold text
        
        Args:
            content: Original content
            section_title: Section title
            
        Returns:
            Cleaned content
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Check if line is a Markdown heading
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # Check if heading duplicates section title (skip within first 5 lines)
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # Convert all heading levels (#, ##, ###, ####, etc.) to bold
                # Section title is added by system, content should not have headings
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # Add blank line
                continue
            
            # If previous line was skipped heading and current is blank, skip too
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # Remove leading blank lines
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # Remove leading separators
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # Also remove blank lines after separator
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        更新报告Generation progress
        
        前端可以通过读取progress.json获取实时进度
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """Get reportGeneration progress"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Get list of generated sections.
        
        Returns all saved section file info.
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Parse section index from filename
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        组装Full report
        
        从已保存的章节文件组装Full report，并进行标题清理
        """
        folder = cls._get_report_folder(report_id)
        
        # Build report header
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # Read all section files in order
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # Post-process: clean heading issues in full report
        md_content = cls._post_process_report(md_content, outline)
        
        # 保存Full report
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(f"Full report已组装: {report_id}")
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        Post-process report content
        
        1. 移除重复的标题
        2. 保留报告主标题(#)和章节标题(##)，移除其他级别的标题(###, ####等)
        3. 清理多余的空行和分隔线
        
        Args:
            content: 原始报告内容
            outline: Report outline
            
        Returns:
            处理后的内容
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # Collect all section titles from outline
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Check if line is a heading
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Check for duplicate heading (same title within 5 lines)
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # Skip duplicate heading and following blank lines
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # Heading level handling:
                # - # (level=1) keep only report main title
                # - ## (level=2) keep section titles
                # - ### and below (level>=3) convert to bold text
                
                if level == 1:
                    if title == outline.title:
                        # Keep report main title
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # Section title incorrectly used #, fix to ##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # Convert other level-1 headings to bold
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # Keep section title
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # Convert non-section level-2 headings to bold
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # Convert ### and below headings to bold text
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # Skip separator immediately after heading
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # Keep only one blank line after heading
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # Clean consecutive blank lines (keep max 2)
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """保存Report metadata和Full report"""
        cls._ensure_report_folder(report.report_id)
        
        # Save metadata JSON
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Save outline
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # Save full Markdown report
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(f"Report saved: {report.report_id}")
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Get report"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # Compatibility: check files stored directly in reports dir
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Rebuild Report object
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # If markdown_content empty, try reading from full_report.md
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """Get report by simulation ID"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # New format: folder
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # Compatibility: JSON file
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """List reports"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # New format: folder
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # Compatibility: JSON file
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # Sort by creation time descending
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """删除报告（整个文件夹)"""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # New format: delete entire folder
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"Report folder deleted: {report_id}")
            return True
        
        # Compatibility: delete individual files
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
