from abc import ABC, abstractmethod
from src.core.context import WorkflowContext

class BaseNode(ABC):
    """
    所有业务节点的抽象基类。
    强制实现 execute 方法，
    保证对外接口的一致性，方便日后接入工作流引擎或 Agent。
    """
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行节点的具体逻辑。
        
        Args:
            context: 包含当前所有进度和数据的上下文对象
            
        Returns:
            修改后的 WorkflowContext，传递给下一个节点
        """
        pass
        
    def log(self, message: str):
        """统一的节点日志输出"""
        print(f"[{self.name}] {message}")