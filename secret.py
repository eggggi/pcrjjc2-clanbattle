import os

from json import load, dump
from hoshino import log, config
from os.path import dirname, join

logger = log.new_logger(__name__, config.DEBUG)
current_folder = dirname(__file__)
secret_folder = join(current_folder, 'secret')

# 继承dict类，重写修改方法，监控修改实时更新json文件
# 性能很差，动一下就更新整个json文件，如果用mongodb的话可以基于这个类做个orm框架
class ObservableDict(dict):
	__parent = None

	def __init__(self, *args, **kwargs):
		self.update(*args, **kwargs)

	def __setitem__(self, key, value):
		super().__setitem__(key, value)
		self.to_parent()

	def __delitem__(self, key):
		super().__delitem__(key)
		self.to_parent()
	
	def __save_file(self):
		group_id = self['group_id']
		sec = join(secret_folder, f'{group_id}.json')
		with open(sec, 'w', encoding="utf-8") as fp:
			dump(self, fp, indent=4, ensure_ascii=False)

	def to_parent(self):
		if self.__parent:
			self.__parent.to_parent()
		else:
			self.__save_file()

	def set_parent(self, parent_dict):
		self.__parent = parent_dict

	def get_parent(self):
		return self.__parent


def initObservableDict(original_dict:dict, parent:ObservableDict = None):
	new_dict:ObservableDict = ObservableDict(original_dict)
	if parent: new_dict.set_parent(parent)
	for k, v in new_dict.items():
		if type(v) == dict:
			new_dict[k] = initObservableDict(v, new_dict)
	return new_dict

class Secret():
	__group_infos = {}

	def __init__(self) -> None:
		for item in os.scandir(secret_folder):
			group_id = item.name.split('.')[0]
			with open(join(secret_folder, f'{group_id}.json'), "r", encoding="utf-8") as fp:
				try: self.__group_infos[group_id] = initObservableDict(load(fp))
				except Exception as e: logger.exception(e)

	def get_sec(self, group_id):
		group_id = str(group_id)
		if group_id not in self.__group_infos: return None
		return self.__group_infos[group_id]

	def save_sec(self, group_id):
		group_id = str(group_id)
		if group_id not in self.__group_infos: return None
		sec = join(secret_folder, f'{group_id}.json')
		with open(sec, 'w', encoding="utf-8") as fp: dump(self.__group_infos[group_id], fp, indent=4, ensure_ascii=False)

	def get_group_infos(self):
		return self.__group_infos

	def add_group_info(self, group_id, group_info):
		group_id = str(group_id)
		self.__group_infos[group_id] = initObservableDict(group_info)
