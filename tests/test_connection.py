# -*- coding: utf-8 -*-
# vim: set expandtab:
import asyncio
import logging
from context import pundun
from pundun import Client
import unittest
import pprint
from pundun import utils
from pundun import constants as enum
from threading import Timer
import concurrent.futures
import time
import logging
import sys

def get_result(future):
    try:
        return future.result(3)
    except asyncio.TimeoutError:
        print('The coroutine took too long, cancelling the task...')
        future.cancel()
        return None
    except Exception as exc:
        print('The coroutine raised an exception: {!r}'.format(exc))
        return None
    else:
        print('The coroutine returned: {!r}'.format(result))
        return None

class TestPundunConnection(unittest.TestCase):
    """Testing pundun connection."""

    def _calls_async(self, client, table_name):
        logging.info('_calls_async for %s', table_name)
        future = client.list_tables(do_async=True)
        tab_exists = table_name in get_result(future)
        logging.info('%s exists %s', table_name, pprint.pformat(tab_exists))
        if tab_exists:
            logging.info('delete_table %s', table_name)
            future = client.delete_table(table_name, do_async=True)
            self.assertTrue(future.result(3))
        logging.info('create_table %s', table_name)
        future = client.create_table(table_name,
                                ['id', 'ts'],
                                {'num_of_shards': 1,
                                 'distributed': False}, do_async=True)
        self.assertTrue(future.result(3))
        timestamp = lambda: int(round(time.time()))
        start_ts = timestamp()-1
        key1 = {'id': '0001', 'ts': time.monotonic()}
        key2 = {'id': '0002', 'ts': time.monotonic()}
        data1 = {'text': 'Coroutines used with asyncio may be implemented.'}
        future = client.write(table_name, key1, data1, do_async=True)
        self.assertTrue(future.result(3))
        data2 = {'text': 'Some irrelevant text here and there'}
        future = client.write(table_name, key2, data2, do_async=True)
        self.assertTrue(future.result(3))
        # Succesful Read Operations
        future = client.read(table_name, key1, do_async=True)
        self.assertEqual(future.result(3), data1)
        future = client.read(table_name, key2, do_async=True)
        self.assertEqual(future.result(3), data2)
        logging.info('_calls_async done')
        return "async_calls_done"

    #@unittest.skip('skip test_thread_pool')
    def test_thread_pool(self):
        logging.info('testing thread pool')
        client = Client('127.0.0.1', 8887, 'admin', 'admin')
        futures = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(client.run_loop)
            for i in range(5):
                table_name = 'python_thread_' + str(i)
                f = executor.submit(self._calls_async, client, table_name)
                futures.append(f)
            for future in concurrent.futures.as_completed(futures, timeout=5):
                try:
                    data = future.result()
                except Exception as exc:
                    logging.error('generated an exception: %s' % exc)
                else:
                    logging.info('future result: %s', pprint.pformat(data))
            executor.submit(client.stop_loop)
        client.cleanup()

    #@unittest.skip('skip test_thread')
    def test_thread(self):
        logging.info("test thread with all sync calls..")
        timer = Timer(0, self._test_all_sync)
        timer.start()

    #@unittest.skip('skip test_main_thread')
    def test_main_thread(self):
        logging.info("testing all sync calls..")
        self._test_all_sync()

    def _test_all_sync(self):
        host = '127.0.0.1'
        port = 8887
        user = 'admin'
        secret = 'admin'
        client = Client(host, port, user, secret)
        table_name = 'pundunpy_test_table'
        timestamp = lambda: int(round(time.time()))
        start_ts = timestamp()-1
        key1 = {'id': '0001', 'ts': time.monotonic()}
        key2 = {'id': '0002', 'ts': time.monotonic()}
        tab_exists = table_name in client.list_tables()
        if tab_exists:
            self.assertTrue(client.delete_table(table_name))
        self.assertTrue(client.create_table(table_name,
                                            ['id', 'ts'],
                                            {'num_of_shards': 1}))
        self.assertEqual(client.read('non_existing_table', key1),
                         ('misc', '{error,"no_table"}'))
        self.assertEqual(client.read(table_name, key1),
                         ('misc', '{error,not_found}'))
        index_config1 = {'column': 'name'}
        index_config2 = {'column': 'text',
                         'index_options': {
                            'char_filter': enum.CharFilter.nfc,
                            'tokenizer': enum.Tokenizer.unicode_word_boundaries,
                            'token_filter': {
                                'transform': enum.TokenTransform.casefold,
                                'add': [],
                                'delete': [],
                                'stats': enum.TokenStats.position
                                }
                            }
                        }
        config = [index_config1, index_config2]
        self.assertTrue(client.add_index(table_name, config))
        data1 = {'name': 'Erdem Aksu',
                 'text': 'Husband Dad and Coder'}
        nested_map = {'some nested int field': 123456,
                      'another nested bin field': b'123456'}
        self.assertTrue(client.write(table_name, key1, data1))
        num = 0x123456789ABCDEF0
        data2 = {'text': 'Some irrelevant text here and there',
                 'is_data': True,
                 'some_int': 900,
                 'bin': utils.uIntToBinaryDefault(num),
                 'blank': None,
                 'double': 99.45,
                 'list': ["str", False, 99, b'bin', None, 3.14],
                 'dict': nested_map}
        self.assertTrue(client.write(table_name, key2, data2))
        # Succesful Read Operations
        self.assertEqual(client.read(table_name, key1), data1)
        self.assertEqual(client.read(table_name, key2), data2)
        posting_list1 = client.index_read(table_name, 'name', 'Erdem Aksu', {
            'sort_by': enum.SortBy.relevance,
            'start_ts': start_ts,
            #'end_ts': timestamp(),
            'max_postings': 5})
        self.assertEqual(posting_list1[0].get('key'), key1)
        posting_list2 = client.index_read(table_name, 'text', 'here', {
            'sort_by': enum.SortBy.relevance,
            'start_ts': start_ts,
            'end_ts': timestamp(),
            'max_postings': 5})
        self.assertEqual(posting_list2[0].get('key'), key2)
        expected_range_res =[(key2, data2), (key1, data1)]
        read_range_res = client.read_range(table_name, key2, key1, 10)
        self.assertEqual(read_range_res['key_columns_list'], expected_range_res)
        read_range_n_res = client.read_range_n(table_name, key2, 2)
        self.assertEqual(read_range_n_res['key_columns_list'],
                         expected_range_res)
        # Iterator operations
        kcp_it2 = client.first(table_name)
        self.assertEqual(kcp_it2['kcp'], (key2, data2))
        kcp1 = client.next(kcp_it2['it'])
        self.assertEqual(kcp1, (key1, data1))
        kcp_it1 = client.seek(table_name, key1)
        self.assertEqual(kcp_it1['kcp'], kcp1)
        kcp2 = client.prev(kcp_it1['it'])
        self.assertEqual(kcp2, (key2, data2))
        error = client.prev(kcp_it1['it'])
        self.assertEqual(error, ('misc', '{error,invalid}'))
        self.assertEqual(client.last(table_name)['kcp'], kcp1)
        # Update operations
        up_ops1 = [
            {'field': 'abc',
             'update_instruction': {'instruction': enum.Instruction.increment,
                                    'threshold': 10,
                                    'set_value': 0},
             'value': 1,
             'default_value': 0}
        ]
        data1.update({'abc': 1})
        self.assertEqual(client.update(table_name, key1, up_ops1), data1)
        up_ops2 = [{'field': 'abc','value': 5}]
        data2.update({'abc': 5})
        self.assertEqual(client.update(table_name, key2, up_ops2), data2)
        # Delete operation
        self.assertTrue(client.delete(table_name, key1))
        self.assertTrue(client.delete(table_name, key2))
        # Table info
        info = client.table_info(table_name, ['index_on'])
        logging.debug("table_info:\n%s", pprint.pformat(info))
        self.assertTrue(client.remove_index(table_name, ['name']))
        all_info = client.table_info(table_name)
        logging.debug("table_info:\n%s", pprint.pformat(all_info))
        client.cleanup()

    #@unittest.skip('skip test_map_key')
    def test_map_key(self):
        host = '127.0.0.1'
        port = 8887
        user = 'admin'
        secret = 'admin'
        logging.info("testing map key..")
        client = Client(host, port, user, secret)
        table_name = 'pundunpy_test_table'
        tab_exists = table_name in client.list_tables()
        if tab_exists:
            self.assertTrue(client.delete_table(table_name))
        self.assertTrue(client.create_table(table_name,
                                            ['id', 'map'],
                                            {'num_of_shards': 1}))
        mymap = {'a': 1, 'b': 1, 'c': 1}
        mymap2 = {'a': 2, 'b': 2, 'c': 2}
        key1 = {'id': 'same', 'map': mymap}
        key2 = {'id': 'same', 'map': mymap2}
        data1 = {'number': '1', 'text': 'One'}
        data2 = {'number': '2', 'text': 'Two'}
        self.assertTrue(client.write(table_name, key1, data1))
        self.assertTrue(client.write(table_name, key2, data2))
        self.assertEqual(client.read(table_name, key1), data1)
        self.assertEqual(client.read(table_name, key2), data2)
        read_range_res = client.read_range(table_name, key2, key1, 2)
        expected_range_res =[(key2, data2), (key1, data1)]
        self.assertEqual(read_range_res['key_columns_list'], expected_range_res)
        client.cleanup()

if __name__ == '__main__':
    utils.setup_logging(level=logging.INFO)
    unittest.main()
