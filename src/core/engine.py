from typing import List
from src.core.context import WorkflowContext
from src.core.base_node import BaseNode

class WorkflowEngine:
    """工作流执行引擎：负责按顺序调度各个 Node"""
    def __init__(self):
        self.nodes: List[BaseNode] = []

    def add_node(self, node: BaseNode):
        self.nodes.append(node)

    def run(self, context: WorkflowContext) -> WorkflowContext:
        print(f"🚀 Starting ClipFlow Engine | Session: {context.session_id}")
        for node in self.nodes:
            node.log("Start executing...")
            context = node.execute(context)
            node.log("Execution finished.")
        print("✅ Workflow completed successfully.")
        return context