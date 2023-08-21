"""Prompts."""


from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Tuple

from llama_index.bridge.langchain import BasePromptTemplate as LangchainTemplate
from llama_index.bridge.langchain import ConditionalPromptSelector as LangchainSelector
from llama_index.llms.base import LLM, ChatMessage
from llama_index.llms.generic_utils import messages_to_prompt, prompt_to_messages
from llama_index.llms.langchain_utils import from_lc_messages
from llama_index.prompts.prompt_type import PromptType
from llama_index.prompts.utils import get_template_vars
from llama_index.types import BaseOutputParser


class BasePromptTemplate(ABC):
    @property
    @abstractmethod
    def metadata(self) -> dict:
        ...

    @property
    @abstractmethod
    def template_vars(self) -> List[str]:
        ...

    @property
    @abstractmethod
    def kwargs(self) -> Dict[str, str]:
        ...

    @property
    @abstractmethod
    def output_parser(self) -> Optional[BaseOutputParser]:
        ...

    @abstractmethod
    def partial_format(self, **kwargs: Any) -> "BasePromptTemplate":
        ...

    @abstractmethod
    def format(self, llm: Optional[LLM] = None, **kwargs: Any) -> str:
        ...

    @abstractmethod
    def format_messages(
        self, llm: Optional[LLM] = None, **kwargs: Any
    ) -> List[ChatMessage]:
        ...


class ChatPromptTemplate(BasePromptTemplate):
    def __init__(
        self,
        message_templates: List[ChatMessage],
        prompt_type: str = PromptType.CUSTOM,
        output_parser: Optional[BaseOutputParser] = None,
        **kwargs: Any,
    ):
        self._message_templates = message_templates

        self.kwargs = kwargs
        self.metadata = {
            "prompt_type": prompt_type,
        }
        self.output_parser = output_parser

    @property
    def template_vars(self) -> List[str]:
        """Get input variables."""
        variables = []
        for message_template in self._message_templates:
            variables.extend(get_template_vars(message_template.content or ""))
        return variables

    def partial_format(self, **kwargs: Any) -> "ChatPromptTemplate":
        prompt = deepcopy(self)
        prompt.kwargs.update(kwargs)
        return prompt

    def format(self, llm: Optional[LLM] = None, **kwargs: Any) -> str:
        del llm  # unused
        messages = self.format_messages(**kwargs)
        prompt = messages_to_prompt(messages)
        return prompt

    def format_messages(
        self, llm: Optional[LLM] = None, **kwargs: Any
    ) -> List[ChatMessage]:
        del llm  # unused
        """Format the prompt into a list of chat messages."""
        all_kwargs = {
            **self.kwargs,
            **kwargs,
        }

        messages = []
        for message_template in self._message_templates:
            template_vars = get_template_vars(message_template.content or "")
            relevant_kwargs = {
                k: v for k, v in all_kwargs.items() if k in template_vars
            }
            content_template = message_template.content or ""
            content = content_template.format(**relevant_kwargs)

            message = message_template.copy()
            message.content = content
            messages.append(message)

        return messages


class PromptTemplate(BasePromptTemplate):
    def __init__(
        self,
        template: str,
        prompt_type: str = PromptType.CUSTOM,
        output_parser: Optional[BaseOutputParser] = None,
        **kwargs: Any,
    ) -> None:
        self._template = template

        self.kwargs = kwargs
        self.metadata = {
            "prompt_type": prompt_type,
        }
        self.output_parser = output_parser

    @property
    def template_vars(self) -> List[str]:
        return get_template_vars(self._template)

    def partial_format(self, **kwargs: Any) -> "PromptTemplate":
        """Partially format the prompt."""
        prompt = deepcopy(self)
        prompt.kwargs.update(kwargs)
        return prompt

    def format(self, llm: Optional[LLM] = None, **kwargs: Any) -> str:
        """Format the prompt into a string."""
        del llm  # unused
        all_kwargs = {
            **self.kwargs,
            **kwargs,
        }
        return self._template.format(**all_kwargs)

    def format_messages(
        self, llm: Optional[LLM] = None, **kwargs: Any
    ) -> List[ChatMessage]:
        """Format the prompt into a list of chat messages."""
        del llm  # unused
        prompt = self.format(**kwargs)
        return prompt_to_messages(prompt)


class SelectorPromptTemplate(BasePromptTemplate):
    def __init__(
        self,
        default_prompt: BasePromptTemplate,
        conditionals: Optional[
            List[Tuple[Callable[[LLM], bool], BasePromptTemplate]]
        ] = None,
    ):
        self.default_prompt = default_prompt
        self.conditionals = conditionals or []

    @property
    def metadata(self) -> dict:
        return self.default_prompt.metadata

    @property
    def kwargs(self) -> Dict[str, str]:
        return self.default_prompt.kwargs

    @property
    def template_vars(self) -> List[str]:
        return self.default_prompt.template_vars

    @property
    def output_parser(self) -> Optional[BaseOutputParser]:
        return self.default_prompt.output_parser

    def _select(self, llm: Optional[LLM] = None) -> BasePromptTemplate:
        if llm is None:
            return self.default_prompt

        for condition, prompt in self.conditionals:
            if condition(llm):
                return prompt
        return self.default_prompt

    def partial_format(self, **kwargs: Any) -> "SelectorPromptTemplate":
        default_prompt = self.default_prompt.partial_format(**kwargs)
        conditionals = [
            (condition, prompt.partial_format(**kwargs))
            for condition, prompt in self.conditionals
        ]
        return SelectorPromptTemplate(
            default_prompt=default_prompt, conditionals=conditionals
        )

    def format(self, llm: Optional[LLM] = None, **kwargs: Any) -> str:
        """Format the prompt into a string."""
        prompt = self._select(llm=llm)
        return prompt.format(**kwargs)

    def format_messages(
        self, llm: Optional[LLM] = None, **kwargs: Any
    ) -> List[ChatMessage]:
        """Format the prompt into a list of chat messages."""
        prompt = self._select(llm=llm)
        return prompt.format_messages(**kwargs)


class LangchainPromptTemplate(BasePromptTemplate):
    def __init__(
        self,
        template: Optional[LangchainTemplate] = None,
        selector: Optional[LangchainSelector] = None,
        prompt_type: str = PromptType.CUSTOM,
    ) -> None:
        if selector is None:
            if template is None:
                raise ValueError("Must provide either template or selector.")
            self._selector = LangchainSelector(default_prompt=template)
        else:
            if template is not None:
                raise ValueError("Must provide either template or selector.")
            self._selector = selector

        self.metadata = {
            "prompt_type": prompt_type,
        }
        self.output_parser = template.output_parser

    @property
    def template_vars(self) -> List[str]:
        return get_template_vars(self._selector.default_prompt)

    def partial_format(self, **kwargs: Any) -> "PromptTemplate":
        """Partially format the prompt."""
        default_prompt = self._selector.default_prompt.partial(**kwargs)
        conditionals = [
            (condition, prompt.partial(**kwargs))
            for condition, prompt in self._selector.conditionals
        ]
        lc_selector = LangchainSelector(
            default_prompt=default_prompt, conditionals=conditionals
        )
        return LangchainPromptTemplate(selector=lc_selector)

    def format(self, llm: Optional[LLM] = None, **kwargs: Any) -> str:
        """Format the prompt into a string."""
        del llm  # unused
        template = self._selector.get_prompt(llm=llm)
        return template.format(**kwargs)

    def format_messages(
        self, llm: Optional[LLM] = None, **kwargs: Any
    ) -> List[ChatMessage]:
        """Format the prompt into a list of chat messages."""
        del llm  # unused
        template = self._selector.get_prompt(llm=llm)
        lc_prompt_value = template.format_prompt(**kwargs)
        lc_messages = lc_prompt_value.to_messages()
        messages = from_lc_messages(lc_messages)
        return messages


# NOTE: only for backwards compatibility
Prompt = PromptTemplate
