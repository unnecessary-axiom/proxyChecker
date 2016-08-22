import logging
import requests

from threading import Thread
import queue
import argparse
import fileinput
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] (%(threadName)-10s) %(message)s',
)

def isGoodProxy(target_address, proxy_string, timeout=8, canary_text=None):
    """ Check the validity of a proxy

    Args:
        target_address: A website address to check
        proxy_string: A proxy address in the format proto://ip:port
        timeout: A connection timeout in seconds
        canary_text: Optional text to check for presense of in the response

    Returns:
        A boolean for proxy validity
    """
    proxies = {
        'http' : proxy_string, 
        'https' : proxy_string, 
    }

    s = requests.Session()
    # Kind of a hacky/nosy inspection to see if I need to apply my retry limit
    if s.adapters['http://'].max_retries != 1 or s.adapters['https://'].max_retries != 1:
        a = requests.adapters.HTTPAdapter(max_retries=1)
        s.mount('http://', a)
        s.mount('https://', a)

    try: 
        response = requests.get(target_address, timeout=timeout, proxies=proxies)
    except requests.exceptions.Timeout as e:
        return False
    except Exception as e:
        logging.debug('Got error "{e}" while checking {p}'.format(
            e=str(e),
            p=proxy_string,
        ))
        return False

    if canary_text:
        return (canary_text in response.text)
    return True

def worker(work_queue, result_queue):
    logging.debug('Starting')
    while True:
        proxy_data = work_queue.get()
        if proxy_data is None:
            break
        logging.debug('Testing {}'.format(proxy_data['proxy_string']))

        test_args = proxy_data.copy()
        if '://' not in test_args['proxy_string']:
            test_args['proxy_string'] = 'http://{}'.format(test_args['proxy_string'])

        if isGoodProxy(**test_args):
            logging.debug('Success for {}'.format(proxy_data['proxy_string']))
            result_queue.put(proxy_data['proxy_string'])
        else:
            logging.debug('Failure for {}'.format(proxy_data['proxy_string']))
        work_queue.task_done()

def printer(result_queue, output_handle):
    logging.debug('Starting')
    while True:
        output_data = result_queue.get()
        if output_data is None:
            break
        logging.debug('Saving {proxy}'.format(
            proxy=output_data
        ))
        output_handle.write(output_data)
        output_handle.write("\n")
        result_queue.task_done()

if __name__ == "__main__":
    NUM_WORKERS=5 # Arbitrary number

    parser = argparse.ArgumentParser(description='Test a list of proxies')
    parser.add_argument(
        '--input',
        required=False,
        help='List of ip:port seperated by newlines'
    )
    parser.add_argument(
        '--output',
        required=False,
        help='An output file to append good proxies to'
    )
    parser.add_argument(
        '--target-address',
        required=False,
        help='A website to test against',
        default='http://checkip.dyndns.com/'
    )
    parser.add_argument(
        '--canary-text',
        required=False,
        help='Some text to check for on the target website'
    )
    parser.add_argument(
        '--timeout',
        required=False,
        help='Timeout in seconds to give up on a proxy',
        default=8,
        type=float,
    )

    args = parser.parse_args()

    logging.debug('Filling work queue')
    work_queue = queue.Queue()
    for line in fileinput.input(args.input):
        line = line.rstrip("\n")
        work_queue.put({
            'target_address': args.target_address,
            'proxy_string': line,
            'timeout': args.timeout,
            'canary_text': args.canary_text,
        })

    result_queue = queue.Queue()

    logging.debug('Starting {} workers'.format(NUM_WORKERS))
    workers = []
    for i in range(NUM_WORKERS):
        w = Thread(
            name='WorkerThread {}'.format(i),
            target=worker,
            args=(work_queue, result_queue)
        )
        workers.append(w)
        w.start()

    if not args.output or args.output == '-':
        out_handle = sys.stdout
    else:
        out_handle = open(args.output, 'w+')

    logging.debug('Starting output worker')
    output_worker = Thread(
        name='WriterThread',
        target=printer,
        args=(result_queue, out_handle)
    )
    output_worker.start()

    work_queue.join()
    logging.debug('Work queue empty')
    result_queue.join()
    logging.debug('Result queue empty')

    for i in range(NUM_WORKERS):
        work_queue.put(None)
    result_queue.put(None)
    for w in workers:
        w.join()
    output_worker.join()
    logging.debug('Cleaned up workers.')

    logging.debug('Done')
