import argparse
import os
from chat_downloader import ChatDownloader
from typing import List

class ChatMessage:
    TimestampSeconds: float
    Author: str
    MessageText: str
    def __init__(self, timestamp_seconds: float, author:str, message_text: str) -> None:
        self.TimestampSeconds = timestamp_seconds
        self.Author = author
        self.MessageText = message_text

class SrtLine:
    Index: int
    StartTimeSeconds: float
    EndTimeSeconds: float
    MessageText: str
    def __init__(self, index: int, start_time_seconds: float, end_time_seconds: float, message_text: str) -> None:
        self.Index = index
        self.StartTimeSeconds = start_time_seconds
        self.EndTimeSeconds = end_time_seconds
        self.MessageText = message_text
    def __seconds_to_timestamp(self, seconds: float):
        int_seconds = int(seconds)
        h, remainder = divmod(abs(int_seconds), 3600)
        m, s = divmod(remainder, 60)
        milliseconds = round(1000 * (float(seconds) - int_seconds))
        return f"{'-' if seconds < 0 else ''}{h:02}:{m:02}:{s:02},{milliseconds:03}"
    def to_string(self) -> str:
        return f'{self.Index}\n{self.__seconds_to_timestamp(self.StartTimeSeconds)} --> {self.__seconds_to_timestamp(self.EndTimeSeconds)}\n{self.MessageText}\n\n'

def even_spaced_timestamp_filter(chat_messages: List[ChatMessage], smoothing_interval_seconds: float = 5):
    """Smooths out chat message timestamps within regularly-spaced intervals, so that timestamps are more evenly-spaced. This helps readability when bursts of several messages occur at nearly the same time."""
    if len(chat_messages) == 0:
        return
    if smoothing_interval_seconds <= 0:
        raise ValueError(f'smoothingIntervalSeconds must be positive, but was {smoothing_interval_seconds}')
    minIndex = 0
    maxIndex = -1
    minTimestamp = 0
    maxTimestamp = smoothing_interval_seconds
    lastTimestamp = chat_messages[-1].TimestampSeconds
    while minTimestamp < lastTimestamp:
        while maxIndex + 1 < len(chat_messages) and chat_messages[maxIndex + 1].TimestampSeconds < maxTimestamp:
            maxIndex += 1
        commentsInInterval = maxIndex - minIndex + 1
        if commentsInInterval > 0:
            for i in range(0, commentsInInterval):
                chat_messages[minIndex + i].TimestampSeconds = minTimestamp + (2 * i + 1) * smoothing_interval_seconds / (2 * commentsInInterval)
        minIndex = maxIndex + 1
        minTimestamp += smoothing_interval_seconds
        maxTimestamp += smoothing_interval_seconds

def parse_chat_messages(chats) -> List[ChatMessage]:
    chatMessages: List[ChatMessage] = []
    for chat in chats:
        messageText: str = chat['message']
        # Replace shorthand emotes, like :partying_face:, with UTF, like 🥳.
        emotes = chat.get('emotes')
        if emotes:
            for emote in emotes:
                utfId = emote['id']
                shortcuts = emote['shortcuts']
                # "Custom emojis" use sprite images, not UTF characters, and SRT cannot display images, so ignore these.
                isNotCustomEmoji = not emote['is_custom_emoji']
                if utfId and shortcuts and isNotCustomEmoji:
                    for shortcut in shortcuts:
                        messageText = messageText.replace(shortcut, utfId)
        chatMessages.append(ChatMessage(
            timestamp_seconds=chat['time_in_seconds'],
            author=chat['author']['name'],
            message_text=messageText))
    return chatMessages

def parse_srt_lines(chat_messages: List[ChatMessage], max_seconds_onscreen: float = 5) -> List[SrtLine]:
    if max_seconds_onscreen <= 0:
        raise ValueError(f'max_seconds_onscreen must be positive, but was {max_seconds_onscreen}')
    srtLines: List[SrtLine] = []
    for index, chatMessage in enumerate(chat_messages):
        nextTimestampSeconds = chat_messages[index + 1].TimestampSeconds if index + 1 < len(chat_messages) else float("inf")
        srtLines.append(SrtLine(
            index=index,
            start_time_seconds=chatMessage.TimestampSeconds,
            end_time_seconds=min(nextTimestampSeconds, chatMessage.TimestampSeconds + max_seconds_onscreen),
            message_text=f'<font color="#00FF00">{chatMessage.Author}</font>: {chatMessage.MessageText}'))
    return srtLines


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--max_seconds_onscreen', required=False, default=5)
    parser.add_argument('--smoothing_interval_seconds', required=False, default=5)
    parser.add_argument('--title', required=False, default='subtitles')
    args = parser.parse_args()

    chatMessages = parse_chat_messages(ChatDownloader().get_chat(args.url))
    even_spaced_timestamp_filter(chatMessages, args.smoothing_interval_seconds)
    srtLines = parse_srt_lines(chatMessages, args.max_seconds_onscreen)

    srtPath = os.path.join(os.getcwd(), f'{args.title}.srt')
    with open(srtPath, 'w', encoding='utf-8') as srtFile:
        for srtLine in srtLines:
            srtFile.write(srtLine.to_string())
        print(f'Wrote SRT subtitles to {srtPath}')
