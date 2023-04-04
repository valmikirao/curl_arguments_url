import re
import sys
import json
from typing import Union, List

Node = Union[List['Node'], str]


def trace_to_data(lines) -> Node:
    returned_data: Node = []
    depth = 0
    stack: List[Node] = [returned_data]

    chomp_re = re.compile(r'\n$')
    prefix_spaces_re = re.compile(r'^ *')

    for line in lines:
        line = chomp_re.sub('', line)
        prefix_spaces = prefix_spaces_re.match(line)
        line_depth = len(prefix_spaces.group())
        line = prefix_spaces_re.sub('', line)

        if line_depth > depth:
            depth += 1
            new_node: Node = []
            stack[-1].append(new_node)
            stack.append(new_node)
        elif line_depth < depth:
            depth -= 1
            stack.pop()
        elif line_depth == depth:
            pass

        stack[-1].append(line)

    return returned_data


def main(fin=sys.stdin) -> None:
    data_out = trace_to_data(fin.readlines())
    json.dump(data_out, sys.stdout, indent=2)


if __name__ == '__main__':
    main()
