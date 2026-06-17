from .base import Parser
from .factory import register_parser, get_parser_for_text
from .generic import GenericParser
from .food_basics import FoodBasicsParser

# register built-in parsers
register_parser(FoodBasicsParser)
register_parser(GenericParser)
