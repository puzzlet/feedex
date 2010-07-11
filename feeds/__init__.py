import imp
import os
import traceback

def reload():
    handler_names = []
    file_path = os.path.dirname(__file__)
    for file_name in os.listdir(file_path):
        if file_name.endswith('.py') and not file_name.startswith('__'):
            handler_names.append(file_name[:-3])
    handlers = []
    paths = [os.path.join(file_path, '..')]
    for handler_name in handler_names:
        module = None
        handler_name = 'feeds.' + handler_name
        try:
            module = __import__(handler_name, fromlist='manager')
        except Exception:
            traceback.print_exc()
            continue
        if getattr(module, 'manager', None):
            handlers.append({
                '__name__': handler_name,
                'manager': module.manager,
            })
    return handlers

