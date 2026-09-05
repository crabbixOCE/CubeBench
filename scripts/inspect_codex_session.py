#!/usr/bin/env python3
"""Extract recorded tool programs/results and structural metadata from a rollout.

Does not execute extracted programs or export message bodies, reasoning bodies,
or internal metadata. The original session remains in its isolated Codex home.
"""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    events = []
    for line in args.session.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # A live session can end with a partially written record.
    counts = Counter()
    calls = []
    results = {}
    reasoning = []
    for event in events:
        p = event.get('payload', {})
        kind = p.get('type', '')
        counts[event['type'] + ':' + kind] += 1
        if event['type'] != 'response_item':
            continue
        if kind in ['custom_tool_call_output', 'function_call_output']:
            results[p.get('call_id')] = p.get('output')
        if kind in ['custom_tool_call', 'function_call']:
            calls.append({'timestamp': event.get('timestamp'), 'call_id': p.get('call_id'),
                          'name': p.get('name'), 'input': p.get('input', p.get('arguments', ''))})
        if kind == 'reasoning':
            reasoning.append({'fields': list(p), 'summary_count': len(p.get('summary', []) or []),
                              'content_count': len(p.get('content', []) or []),
                              'encrypted_content_chars': len(p.get('encrypted_content', '') or '')})
    for index, call in enumerate(calls):
        stem = f'{index + 1:03d}'
        suffix = '.js' if call['name'] == 'exec' else '.txt'
        program = args.output / (stem + suffix)
        program.write_text(call.pop('input'))
        call['program'] = str(program)
        call['has_result'] = call['call_id'] in results
        if call['has_result']:
            result = args.output / (stem + '.output.json')
            result.write_text(json.dumps(results[call['call_id']], indent=2))
            call['result'] = str(result)
            value = results[call['call_id']]
            if isinstance(value, str):
                readable = args.output / (stem + '.output.txt')
                readable.write_text(value)
                call['readable_result'] = str(readable)
            if isinstance(value, list):
                blocks = []
                for block in value:
                    text = block.get('text', '')
                    try:
                        text = json.dumps(json.loads(text), indent=2)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    blocks.append(text)
                readable = args.output / (stem + '.output.txt')
                readable.write_text('\n\n'.join(blocks))
                call['readable_result'] = str(readable)
    report = {'session': str(args.session), 'records': len(events),
              'record_types': dict(counts), 'calls': calls, 'reasoning_structure': reasoning}
    (args.output / 'index.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'records': len(events), 'tool_calls': len(calls),
                      'tool_names': dict(Counter(c['name'] for c in calls)),
                      'reasoning_items': len(reasoning)}))


if __name__ == '__main__':
    main()
