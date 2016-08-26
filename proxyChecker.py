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

def isGoodProxy(target_address, proxy_string, proxy_type, timeout=8, text_present=None, text_absent=True):
    """ Check the validity of a proxy

    Args:
        target_address: A website address to check
        proxy_string: A proxy address in the format ip:port
        proxy_type: Type of proxy to test for. socks4/5 or http
        timeout: A connection timeout in seconds
        text_present: Optional text to check for presense of in the response
        text_absent: Optional text to check for absence of in the response

    Returns:
        A dict:
            {
                'proxy_string': [String of addr:port],
                'proxy_type': [whatever type you passed in],
                'success': [Bool],
                'response_time': [response time in timedelta format],
            }
    """
    if 'socks' not in proxy_type.lower() and 'http' not in proxy_type.lower():
        raise Exception('Invalid proxy type {}'.format(proxy_type))

    proxies = {
        'http' : '{}://{}'.format(proxy_type.lower(), proxy_string),
        'https' : '{}://{}'.format(proxy_type.lower(), proxy_string),
    }

    try: 
        response = requests.get(target_address, timeout=timeout, proxies=proxies)
    except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as e:
        return {
            'proxy_string': proxy_string,
            'proxy_type': proxy_type,
            'success': False,
            'response_time': None,
        }
    except Exception as e:
        logging.debug('Got error "{e}" while checking {p}'.format(
            e=str(e),
            p=proxy_string,
        ))
        return {
            'proxy_string': proxy_string,
            'proxy_type': proxy_type,
            'success': False,
            'response_time': None,
        }

    present_flag = (text_present is None or (text_present in response.text))
    if not present_flag:
        logging.debug("Missing supposedly present text in resposne for {}".format(proxy_string))

    absent_flag = (text_absent is None or (text_absent not in response.text))
    if not absent_flag:
        logging.debug("Found supposedly absent text in resposne for {}".format(proxy_string))

    success = present_flag and absent_flag
    return {
        'proxy_string': proxy_string,
        'proxy_type': proxy_type,
        'success': success,
        'response_time': response.elapsed,
    }


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

        logging.info('Testing {} for {}'.format(
            proxy_data['proxy_string'],
            proxy_data['proxy_type']
        ))
        results = isGoodProxy(**proxy_data)
        if results['success']:
            logging.info('Success for {} for {}'.format(
                proxy_data['proxy_string'],
                proxy_data['proxy_type']
            ))
            result_queue.put(results)
        else:
            logging.info('Failure for {} for {}'.format(
                proxy_data['proxy_string'],
                proxy_data['proxy_type']
            ))

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
            output_data['proxy_type'],
        ))
        output_handle.write('{},{:.2f},{}'.format(
            output_data['proxy_type'],
            output_data['response_time'].seconds + output_data['response_time'].microseconds / 10000000,
            output_data['proxy_string'],
        ))
        output_handle.write("\n")
        result_queue.task_done()

def clean_addresses(addresses, blacklist=[]):

    # Parse and validate passed addresses
    parsed_addresses = []
    for address in addresses:
        (ip, port) = address.split(':')
        try:
            netip = netaddr.IPAddress(ip)
            parsed_addresses.append((address, netip))
        except netaddr.AddrFormatError as e:
            logging.info("Malformed address {}, skipping".format(ip))
            continue

    # Fill a list of parsed blacklist entries
    ranges = []
    for block in blacklist:
        try:
            if '-' in block:
                start, end = block.split('-')
                ranges.append(netaddr.IPRange(start, end))
            else:
                ranges.append(netaddr.IPNetwork(block))
        except netaddr.AddrFormatError as e:
            raise Exception("Error importing blocks: {}".format(block)) from e

    # Shortcut if we have no blacklist ranges
    if not ranges:
        return [i[0] for i in parsed_addresses]

    # Clean each address against the blacklist
    clean = []
    for addr in parsed_addresses:
        proxy, netip = addr
        intersection = next((r for r in ranges if (netip in r)), None)
        if intersection is None:
            clean.append(proxy)
        else:
            logging.info("Proxy {} in exclusion list".format(proxy))
    return clean

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
        '--text-present',
        required=False,
        help='Some text that should be present on the target website. For example, some words you know exist.'
    )
    parser.add_argument(
        '--text-absent',
        required=False,
        help='Some text that should be absent on the target website. For example, your public IP.'
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
        help='List of types of proxies to check for. Allows socks4, socks5, http',
        nargs='*',
        choices=['http', 'socks4', 'socks5'],
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

    exclusions = []
    if args.exclusion_list:
        logging.info('Creating exclusion list')
        with open(args.exclusion_list, 'r') as f:
            for block in f:
                block = block.rstrip("\n")
                if block and block[0] != '#':
                    exclusions.append(block)

    logging.info('Cleaning addresses')
    # This list is removed a couple lines down after we fill the queue
    good_proxies = clean_addresses(loaded_proxies, exclusions)

    logging.info('Filling work queue')
    for proxy in good_proxies:
        for ptype in args.proxy_type:
            work_queue.put({
                'target_address': args.target_address,
                'proxy_string': proxy,
                'timeout': args.timeout,
                'text_present': args.text_present,
                'text_absent': args.text_absent,
                'proxy_type': ptype,
            })
    del(good_proxies)

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
