EXAMPLE = {
# job.py
    'job.py': """
import logging

from signac.contrib import get_project

# This list defines the parameter space.
state_points = [{'a': a, 'b': b} for a in range(3) for b in range(3)]

# The code to be executed for each state point.
def run_job(state_point):
    project = get_project()
    with project.open_job(state_point) as job:
        # Replace the following example with actual code
        my_result = job.parameters()['a'] + job.parameters()['b']
        job.document['my_result'] = my_result
        print("Hello world!", my_result)
        from time import sleep
        sleep(5)

def main():
    for state_point in state_points:
        run_job(state_point)

if __name__ == '__main__':
    logging.basicConfig(level = logging.WARNING)
    main()""",
# analyze.py
    'analyze.py': """
import logging
from signac.contrib import get_project

def main():
    project = get_project()
    docs = project.find()
    for doc in docs:
        print(doc['my_result'])

if __name__ == '__main__':
    logging.basicConfig(level = logging.WARNING)
    main()"""
}
