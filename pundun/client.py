import asyncio
import pprint
import logging
from pundun import apollo_pb2 as apollo
from pundun import utils
import scram
import sys

class Client:
    """Client class including pundun procedures."""

    def __init__(self, host, port, user, password):
        logging.info('Client setup..')
        self.host = host
        self.port = port
        self.username = user
        self.password = password
        #self.loop.run_forever()
        self.tid = 0
        self.cid = 0
        self.message_dict = {}
        self.loop = asyncio.get_event_loop()
        (self.reader, self.writer) = self._connect(self.loop)
        asyncio.ensure_future(self._listener())

    def __del__(self):
        logging.info('Client cleanup..')
        self._disconnect()
        self.loop.close()

    #@asyncio.coroutine
    def _listener(self):
        logging.debug('listener started..')
        while self.loop.is_running():
            try:
                len_bytes = yield from self.reader.readexactly(4)
                length = int.from_bytes(len_bytes, byteorder='big')
                cid_bytes = yield from self.reader.readexactly(2)
                cid = int.from_bytes(cid_bytes, byteorder='big')
                data = yield from self.reader.readexactly(length-2)
                q = self.message_dict[cid]
                q.put_nowait(data)
                logging.debug('put q: %s', pprint.pformat(q))
            except:
                logging.error('Listener Exception: {}'.format(sys.exc_info()[0]))
                break

    def _connect(self, loop):
        (reader, writer) = scram.connect(self.host, self.port, loop = loop)
        res = scram.authenticate(self.username, self.password,
                                 streamreader = reader,
                                 streamwriter = writer,
                                 loop = self.loop)
        logging.debug('Scrampy Auth response: {}'.format(res))
        return (reader, writer)

    def _disconnect(self):
        return scram.disconnect(streamwriter = self.writer,
                                loop = self.loop)

    def create_table(self, table_name, key_def, options):
        return self.loop.run_until_complete(self._create_table(table_name,
                                                               key_def,
                                                               options))

    def _create_table(self, table_name, key_def, options):
        pdu = self._make_pdu()
        pdu.create_table.table_name = table_name
        pdu.create_table.keys.extend(key_def)
        table_options = utils.make_table_options(options)
        pdu.create_table.table_options.extend(table_options)
        rpdu = yield from self._write_pdu(pdu)
        return utils.format_rpdu(rpdu)

    def delete_table(self, table_name):
        return self.loop.run_until_complete(self._delete_table(table_name))

    def _delete_table(self, table_name):
        pdu = self._make_pdu()
        pdu.delete_table.table_name = table_name
        rpdu = yield from self._write_pdu(pdu)
        return utils.format_rpdu(rpdu)

    def read(self, table_name, key):
        return self.loop.run_until_complete(self._read(table_name, key))

    def _read(self, table_name, key):
        pdu = self._make_pdu()
        pdu.read.table_name = table_name
        key_fields = utils.make_fields(key)
        pdu.read.key.extend(key_fields)
        rpdu = yield from self._write_pdu(pdu)
        return utils.format_rpdu(rpdu)

    def add_index(self, table_name, config):
        return self.loop.run_until_complete(self._add_index(table_name, config))

    def _add_index(self, table_name, config):
        pdu = self._make_pdu()
        pdu.add_index.table_name = table_name
        pdu.add_index.config.extend(utils.make_index_config_list(config))
        rpdu = yield from self._write_pdu(pdu)
        return utils.format_rpdu(rpdu)

    def list_tables(self):
        return self.loop.run_until_complete(self._list_tables())

    def _list_tables(self):
        pdu = self._make_pdu()
        pdu.list_tables.SetInParent()
        rpdu = yield from self._write_pdu(pdu)
        return utils.format_rpdu(rpdu)

    def _make_pdu(self):
        pdu = apollo.ApolloPdu()
        pdu.version.major = 0
        pdu.version.minor = 1
        return pdu

    def _write_pdu(self, pdu):
        pdu.transaction_id = self._get_tid()
        logging.debug('pdu: %s', pprint.pformat(pdu))
        data = pdu.SerializeToString()
        logging.debug('encoded pdu: %s', pprint.pformat(data))
        cid = self._get_cid()
        cid_bytes = cid.to_bytes(2, byteorder='big')
        length = len(data) + 2
        len_bytes = length.to_bytes(4, byteorder='big')
        logging.debug('len_bytes: %s', pprint.pformat(len_bytes))
        logging.debug('cid_bytes: %s', pprint.pformat(cid_bytes))
        msg = b''.join([len_bytes,cid_bytes, data])
        logging.debug('send bytes %s', pprint.pformat(msg))
        self.writer.write(msg)
        q = asyncio.Queue(maxsize = 1, loop=self.loop)
        self.message_dict[cid] = q
        rdata = yield from q.get()
        logging.debug('received data: %s', pprint.pformat(rdata))
        del self.message_dict[cid]
        rpdu = apollo.ApolloPdu()
        rpdu.ParseFromString(rdata)
        return rpdu

    def _get_tid(self):
        tid = self.tid
        if self.tid == 4294967295:
            self.tid = 0
        else:
            self.tid += 1
        return tid

    def _get_cid(self):
        cid = self.cid
        if self.cid == 65535:
            self.cid = 0
        else:
            self.cid += 1
        return cid