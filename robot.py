import torch
import os
import numpy as np
from datetime import datetime
from os.path import join, exists
from transformers import GPT2LMHeadModel
from transformers import BertTokenizerFast
import argparse
import logging
import torch.nn.functional as F

class robot:
    '''
    初始化一些变量
    '''
    def __init__(self,robotName):
        self.robotName = robotName
        self.args = self.set_args()
        self.logger = self.create_logger(self.args)

        # 当用户使用GPU,并且GPU可用时
        self.args.cuda = torch.cuda.is_available() and not self.args.no_cuda
        self.device = 'cuda' if self.args.cuda else 'cpu'
        self.logger.info('using device:{}'.format(self.device))
        os.environ["CUDA_VISIBLE_DEVICES"] = self.args.device
        self.tokenizer = BertTokenizerFast(vocab_file=self.args.vocab_path, sep_token="[SEP]", pad_token="[PAD]", cls_token="[CLS]")
        self.model = GPT2LMHeadModel.from_pretrained(self.args.model_path)
        self.model = self.model.to(self.device)
        self.model.eval()
        if self.args.save_samples_path:
            if not os.path.exists(self.args.save_samples_path):
                os.makedirs(self.args.save_samples_path)
            self.samples_file = open(self.args.save_samples_path + '/samples.txt', 'a', encoding='utf8')
            self.samples_file.write("聊天记录{}:\n".format(datetime.now()))
        # 存储聊天记录，每个utterance以token的id的形式进行存储
        self.history = []
    
    '''
    对话接口
    '''
    def chitChat(self,message):
        try:
            text = message
            if self.args.save_samples_path:
                self.samples_file.write("user:{}\n".format(text))
            text_ids = self.tokenizer.encode(text, add_special_tokens=False)
            self.history.append(text_ids)
            input_ids = [self.tokenizer.cls_token_id]  # 每个input以[CLS]为开头

            for history_id, history_utr in enumerate(self.history[-self.args.max_history_len:]):
                input_ids.extend(history_utr)
                input_ids.append(self.tokenizer.sep_token_id)
            input_ids = torch.tensor(input_ids).long().to(self.device)
            input_ids = input_ids.unsqueeze(0)
            response = []  # 根据context，生成的response
            # 最多生成max_len个token
            for _ in range(self.args.max_len):
                outputs = self.model(input_ids=input_ids)
                logits = outputs.logits
                next_token_logits = logits[0, -1, :]
                # 对于已生成的结果generated中的每个token添加一个重复惩罚项，降低其生成概率
                for id in set(response):
                    next_token_logits[id] /= self.args.repetition_penalty
                next_token_logits = next_token_logits / self.args.temperature
                # 对于[UNK]的概率设为无穷小，也就是说模型的预测结果不可能是[UNK]这个token
                next_token_logits[self.tokenizer.convert_tokens_to_ids('[UNK]')] = -float('Inf')
                filtered_logits = self.top_k_top_p_filtering(next_token_logits, top_k=self.args.topk, top_p=self.args.topp)
                # torch.multinomial表示从候选集合中无放回地进行抽取num_samples个元素，权重越高，抽到的几率越高，返回元素的下标
                next_token = torch.multinomial(F.softmax(filtered_logits, dim=-1), num_samples=1)
                if next_token == self.tokenizer.sep_token_id:  # 遇到[SEP]则表明response生成结束
                    break
                response.append(next_token.item())
                input_ids = torch.cat((input_ids, next_token.unsqueeze(0)), dim=1)
                # his_text = tokenizer.convert_ids_to_tokens(curr_input_tensor.tolist())
                # print("his_text:{}".format(his_text))
            self.history.append(response)
            text = self.tokenizer.convert_ids_to_tokens(response)
            if self.args.save_samples_path:
                self.samples_file.write(self.robotName + ":{}\n".format("".join(text)))
        except KeyboardInterrupt:
            if self.args.save_samples_path:
                self.samples_file.close()
        return text

    '''
    功能函数
    '''
    def top_k_top_p_filtering(self,logits, top_k=0, top_p=0.0, filter_value=-float('Inf')):
        """ Filter a distribution of logits using top-k and/or nucleus (top-p) filtering
            Args:
                logits: logits distribution shape (vocab size)
                top_k > 0: keep only top k tokens with highest probability (top-k filtering).
                top_p > 0.0: keep the top tokens with cumulative probability >= top_p (nucleus filtering).
                    Nucleus filtering is described in Holtzman et al. (http://arxiv.org/abs/1904.09751)
            From: https://gist.github.com/thomwolf/1a5a29f6962089e871b94cbd09daf317
        """
        assert logits.dim() == 1  # batch size 1 for now - could be updated for more but the code would be less clear
        top_k = min(top_k, logits.size(-1))  # Safety check
        if top_k > 0:
            # Remove all tokens with a probability less than the last token of the top-k
            # torch.topk()返回最后一维最大的top_k个元素，返回值为二维(values,indices)
            # ...表示其他维度由计算机自行推断
            indices_to_remove = logits < torch.topk(logits, top_k)[0][..., -1, None]
            logits[indices_to_remove] = filter_value  # 对于topk之外的其他元素的logits值设为负无穷

        if top_p > 0.0:
            sorted_logits, sorted_indices = torch.sort(logits, descending=True)  # 对logits进行递减排序
            cumulative_probs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)

            # Remove tokens with cumulative probability above the threshold
            sorted_indices_to_remove = cumulative_probs > top_p
            # Shift the indices to the right to keep also the first token above the threshold
            sorted_indices_to_remove[..., 1:] = sorted_indices_to_remove[..., :-1].clone()
            sorted_indices_to_remove[..., 0] = 0

            indices_to_remove = sorted_indices[sorted_indices_to_remove]
            logits[indices_to_remove] = filter_value
        return logits

    '''
    获取控制台初始化参数
    '''
    def set_args(self):
        """
        读取参数设置
        """
        parser = argparse.ArgumentParser()
        parser.add_argument('--device', default='0', type=str, required=False, help='生成设备')
        parser.add_argument('--temperature', default=1, type=float, required=False, help='生成的temperature')
        parser.add_argument('--topk', default=8, type=int, required=False, help='最高k选1')
        parser.add_argument('--topp', default=0, type=float, required=False, help='最高积累概率')
        parser.add_argument('--log_path', default='data/interact.log', type=str, required=False, help='interact日志存放位置')
        parser.add_argument('--vocab_path', default='vocab/vocab.txt', type=str, required=False, help='选择词库')
        parser.add_argument('--model_path', default='model/model_epoch40_50w', type=str, required=False, help='对话模型路径')
        parser.add_argument('--save_samples_path', default="sample/", type=str, required=False, help="保存聊天记录的文件路径")
        parser.add_argument('--repetition_penalty', default=1.0, type=float, required=False,help="重复惩罚参数，若生成的对话重复性较高，可适当提高该参数")
        parser.add_argument('--max_len', type=int, default=25, help='每个utterance的最大长度,超过指定长度则进行截断')
        parser.add_argument('--max_history_len', type=int, default=3, help="dialogue history的最大长度")
        parser.add_argument('--no_cuda', action='store_true', help='不使用GPU进行预测')
        return parser.parse_args()

    '''
    创建日志
    '''
    def create_logger(self,args):
        """
        将日志输出到日志文件和控制台
        """
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        # 创建一个handler，用于写入日志文件
        file_handler = logging.FileHandler(filename=args.log_path)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        # 创建一个handler，用于将日志输出到控制台
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(formatter)
        logger.addHandler(console)
        return logger