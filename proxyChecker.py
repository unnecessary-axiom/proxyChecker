import logging
import requests

from threading import Thread
import netaddr
import queue
import argparse
import fileinput
import time
import sys

logging.basicConfig(
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

    try: 
        response = requests.get(target_address, timeout=timeout, proxies=proxies)
    except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as e:
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
    """ A worker to be used with threading that tests proxies.

    Args:
        work_queue: a queue.Queue that is full of proxy data dicts. 
            When fed None, stops processing.
        result_queue: a queue.Queue to send the successful proxies to
    """
    logging.debug('Starting')
    while True:
        proxy_data = work_queue.get()
        if proxy_data is None:
            break

        #TODO: Clean up ugly double code
        proxy_type = proxy_data.pop('type')

        if proxy_type in ('http', 'both'):
            logging.debug('Testing {} for {}'.format(proxy_data['proxy_string'], 'http'))
            test_args = proxy_data.copy()
            test_args['proxy_string'] = 'http://{}'.format(test_args['proxy_string'])

            if isGoodProxy(**test_args):
                logging.debug('Success for {} for {}'.format(proxy_data['proxy_string'], 'http'))
                result_queue.put({
                    'proxy_string': proxy_data['proxy_string'],
                    'type': 'http',
                })
            else:
                logging.debug('Failure for {} for {}'.format(proxy_data['proxy_string'], 'http'))

        if proxy_type in ('socks', 'both'):
            logging.debug('Testing {} for {}'.format(proxy_data['proxy_string'], 'socks'))
            test_args = proxy_data.copy()
            test_args['proxy_string'] = 'socks5://{}'.format(test_args['proxy_string'])

            if isGoodProxy(**test_args):
                logging.debug('Success for {} for {}'.format(proxy_data['proxy_string'], 'socks'))
                result_queue.put({
                    'proxy_string': proxy_data['proxy_string'],
                    'type': 'socks',
                })
            else:
                logging.debug('Failure for {} for {}'.format(proxy_data['proxy_string'], 'socks'))
        work_queue.task_done()

def printer(result_queue, output_handle):
    """ A worker to be used with threading that prints output.
    There should only be one of these

    Args:
        result_queue: A queue.Queue full of proxy results
        output_handle: Handle to a file like object to receive results
    """
    logging.debug('Starting')
    while True:
        output_data = result_queue.get()
        if output_data is None:
            break
        logging.debug('Saving {} type {}'.format(
            output_data['proxy_string'],
            output_data['type'],
        ))
        output_handle.write('{},{}'.format(
            output_data['type'],
            output_data['proxy_string']
        ))
        output_handle.write("\n")
        result_queue.task_done()

if __name__ == "__main__":
    log_levels = {
        'ERROR': logging.ERROR,
        'WARNING': logging.WARNING,
        'INFO': logging.INFO,
        'DEBUG': logging.DEBUG,
    }

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
        help='A website to test against. Default is a checkIP page.',
        default='http://checkip.dyndns.com/'
    )
    parser.add_argument(
        '--canary-text',
        required=False,
        help='Some text to check for on the target website.'
    )
    parser.add_argument(
        '--timeout',
        required=False,
        help='Timeout in seconds to give up on a proxy. Default 5',
        default=5,
        type=float,
    )
    parser.add_argument(
        '--proxy-type',
        choices=['http', 'socks', 'both'],
        help='Type of proxies to check for. Default http.',
        default='http'
    )
    parser.add_argument(
        '--log-level',
        choices=log_levels.keys(),
        default='WARNING',
        help='Logging verbosity level',
    )
    parser.add_argument(
        '--num-workers',
        type=int,
        help='The number of worker threads to split into. Default 10',
        default=10
    )
    parser.add_argument(
        '--exclusion-list',
        help='A list of IP block seperated by whitespace to not check',
    )

    args = parser.parse_args()

    # Set logging level from args
    logging.getLogger().setLevel(
        log_levels[args.log_level]
    )

    # Create a work queue
    work_queue = queue.Queue()

    # Read input line by line into a list
    # Read from a file or stdin
    loaded_proxies = []
    logging.info('Reading work list')
    for line in fileinput.input(args.input):
        line = line.rstrip("\n")
        loaded_proxies.append(line)

    if args.exclusion_list:
        logging.info('Creating exclusion list')
        ranges = []
        with open(args.exclusion_list, 'r') as f:
            for block in f:
                begin, end = block.split()[:2]
                try:
                    ranges.append(netaddr.IPRange(begin, end))
                except netaddr.AddrFormatError as e:
                    raise Exception("Error importing blocks: {} - {}".format(begin, end)) from e

        logging.info('Checking against list')
        # Check against ranges
        good_proxies = []
        # TODO: DO THIS BETTER?
        for proxy in loaded_proxies:
            (ip, port) = proxy.split(':')
            try:
                addr = netaddr.IPAddress(ip)
            except netaddr.AddrFormatError as e:
                logging.info("Malformed address {}, skipping".format(ip))
                continue
            intersection = next((r for r in ranges if (addr in r)), None)
            if intersection is None:
                good_proxies.append(proxy)
            else:
                logging.info("Proxy {} in exclusion list".format(proxy))
    else:
        good_proxies = loaded_proxies

    logging.info('Filling work queue')
    for proxy in good_proxies:
        work_queue.put({
            'target_address': args.target_address,
            'proxy_string': proxy,
            'timeout': args.timeout,
            'canary_text': args.canary_text,
            'type': args.proxy_type,
        })
    del(good_proxies)
    del(loaded_proxies)

    # Create a result queue
    result_queue = queue.Queue()

    # Start tester workers
    logging.info('Starting {} workers'.format(args.num_workers))
    workers = []
    for i in range(args.num_workers):
        w = Thread(
            name='WorkerThread {}'.format(i),
            target=worker,
            args=(work_queue, result_queue)
        )
        workers.append(w)
        w.start()

    # Grab an output handle. File or stdout
    if not args.output or args.output == '-':
        out_handle = sys.stdout
    else:
        out_handle = open(args.output, 'w+')

    # Start the worker to output successes
    logging.info('Starting output worker')
    output_worker = Thread(
        name='WriterThread',
        target=printer,
        args=(result_queue, out_handle)
    )
    output_worker.start()

    # Wait until work queue is finished
    work_queue.join()
    logging.info('Work queue empty')
    # Wait until results are all saved
    result_queue.join()
    logging.info('Result queue empty')

    # Send a stop signal to all workers
    for i in range(args.num_workers):
        work_queue.put(None)
    result_queue.put(None)
    for w in workers:
        w.join()
    output_worker.join()
    logging.info('Cleaned up workers.')

    # Done!
    logging.info('Done')
