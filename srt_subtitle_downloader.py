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
    Author: str
    MessageText: str
    def __init__(self, index: int, start_time_seconds: float, end_time_seconds: float, author: str, message_text: str) -> None:
        self.Index = index
        self.StartTimeSeconds = start_time_seconds
        self.EndTimeSeconds = end_time_seconds
        self.Author = author
        self.MessageText = message_text
    def __seconds_to_timestamp(self, seconds: float):
        int_seconds = int(seconds)
        h, remainder = divmod(abs(int_seconds), 3600)
        m, s = divmod(remainder, 60)
        milliseconds = round(1000 * (float(seconds) - int_seconds))
        return f"{'-' if seconds < 0 else ''}{h:02}:{m:02}:{s:02},{milliseconds:03}"
    def to_string(self) -> str:
        return f'{self.Index}\n{self.__seconds_to_timestamp(self.StartTimeSeconds)} --> {self.__seconds_to_timestamp(self.EndTimeSeconds)}\n<font color="#00FF00">{self.Author}</font>: {self.MessageText}\n\n'

assHeader = """[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 640
PlayResY: 480
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Myriad Web Pro Condensed,26,&H00ffffff,&H0000ffff,&H0025253a,&H96000000,0,0,0,0,100,100,0,0.00,1,2,1,2,15,15,20,1

[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text
"""

class AssLine:
    StartTimeSeconds: float
    EndTimeSeconds: float
    Author: str
    MessageText: str
    def __init__(self, start_time_seconds: float, end_time_seconds: float, author: str, message_text: str) -> None:
        self.StartTimeSeconds = start_time_seconds
        self.EndTimeSeconds = end_time_seconds
        self.Author = author
        self.MessageText = message_text
    def __seconds_to_timestamp(self, seconds: float):
        int_seconds = int(seconds)
        h, remainder = divmod(abs(int_seconds), 3600)
        m, s = divmod(remainder, 60)
        hundredths = round(100 * (float(seconds) - int_seconds))
        return f"{'-' if seconds < 0 else ''}{h:01}:{m:02}:{s:02}.{hundredths:02}"
    def to_string(self) -> str:
        fadeMilliseconds = round(1000 * (self.EndTimeSeconds - self.StartTimeSeconds) / 20)
        return f'Dialogue: 0,{self.__seconds_to_timestamp(self.StartTimeSeconds)},{self.__seconds_to_timestamp(self.EndTimeSeconds)},,,0000,0000,0000,,{{\\move(320,480,320,360)}}{{\\fad({fadeMilliseconds},{fadeMilliseconds})}}{{\\1c&H00FF00&}}{self.Author}: {{\\1c&HFFFFFF&}}{self.MessageText}\n'

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
            author=chatMessage.Author,
            message_text=chatMessage.MessageText))
    return srtLines

def parse_ass_lines(chat_messages: List[ChatMessage], max_seconds_onscreen: float = 5, grouping_interval_seconds: float = 5, max_subtitles_onscreen: int = 5) -> List[AssLine]:
    if max_seconds_onscreen <= 0:
        raise ValueError(f'max_seconds_onscreen must be positive, but was {max_seconds_onscreen}')
    if grouping_interval_seconds <= 0:
        raise ValueError(f'grouping_interval_seconds must be positive, but was {grouping_interval_seconds}')
    if max_subtitles_onscreen <= 0:
        raise ValueError(f'max_subtitles_onscreen must be positive, but was {max_seconds_onscreen}')
    assLines: List[AssLine] = []
    if len(chat_messages) == 0:
        return assLines
    minTimestamp = 0
    maxTimestamp = grouping_interval_seconds
    lastTimestamp = chat_messages[-1].TimestampSeconds
    minIndex = 0
    maxIndex = -1
    while minTimestamp < lastTimestamp:
        while maxIndex + 1 < len(chat_messages) and chat_messages[maxIndex + 1].TimestampSeconds < maxTimestamp:
            maxIndex += 1
        commentsInInterval = maxIndex - minIndex + 1
        if commentsInInterval > 0:
            subtitlesPerSecond = commentsInInterval / grouping_interval_seconds
            for i in range(0, commentsInInterval):
                chatMessage = chat_messages[minIndex + i]
                timeOnscreen = min(max_subtitles_onscreen / subtitlesPerSecond, max_seconds_onscreen)
                assLines.append(AssLine(
                    start_time_seconds=chatMessage.TimestampSeconds,
                    end_time_seconds=chatMessage.TimestampSeconds + timeOnscreen,
                    author=chatMessage.Author,
                    message_text=chatMessage.MessageText))
        minIndex = maxIndex + 1
        minTimestamp += grouping_interval_seconds
        maxTimestamp += grouping_interval_seconds
    return assLines

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--max_seconds_onscreen', required=False, default=5)
    parser.add_argument('--smoothing_interval_seconds', required=False, default=10)
    parser.add_argument('--title', required=False, default='subtitles')

    subparsers = parser.add_subparsers(dest='command', required=True)
    parser_srt = subparsers.add_parser('srt')
    parser_ass = subparsers.add_parser('ass')
    parser_ass.add_argument('--max_subtitles_onscreen', required=False, default = 5)

    args = parser.parse_args()

    chat = ChatDownloader().get_chat(args.url)
    chatMessages = parse_chat_messages(chat)
    even_spaced_timestamp_filter(chatMessages, args.smoothing_interval_seconds)

    if args.command == 'srt':
        lines = parse_srt_lines(chatMessages, args.max_seconds_onscreen)
    elif args.command == 'ass':
        lines = parse_ass_lines(chatMessages, args.max_seconds_onscreen, args.smoothing_interval_seconds, args.max_subtitles_onscreen)

    filePath = os.path.join(os.getcwd(), f'{args.title}.{args.command}')
    with open(filePath, 'w', encoding='utf-8') as file:
        if args.command == 'ass':
            file.write(assHeader)
        for line in lines:
            file.write(line.to_string())
        print(f'Wrote subtitles to {filePath}')
