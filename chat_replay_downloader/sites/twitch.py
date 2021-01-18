import re
import json
import time
import socket
import base64

from .common import (
    Chat,
    ChatDownloader,
    Timeout
)

from requests.exceptions import RequestException

from ..errors import (
    TwitchError,
    InvalidParameter,
    UnexpectedHTML,
    NoChatReplay
)

from ..utils import (
    ensure_seconds,
    timestamp_to_microseconds,
    seconds_to_time,
    try_get,
    int_or_none,
    replace_with_underscores,
    multi_get,
    update_dict_without_overwrite,
    log,
    remove_prefixes,
    attempts
)

# TODO export as another module?


class TwitchChatIRC():
    _CURRENT_CHANNEL = None

    def __init__(self):
        # create new socket
        self._SOCKET = socket.socket()

        # start connection
        self._SOCKET.connect(('irc.chat.twitch.tv', 6667))
        # print('Connected to', self._HOST, 'on port', self._PORT)

        # https://dev.twitch.tv/docs/irc/tags
        # https://dev.twitch.tv/docs/irc/membership
        # https://dev.twitch.tv/docs/irc/commands

        # twitch.tv/membership
        self.send_raw(
            'CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership')
        self.send_raw('PASS SCHMOOPIIE')
        self.send_raw('NICK justinfan67420')

    def send_raw(self, string):
        self._SOCKET.send((string+'\r\n').encode('utf-8'))

    def recv(self, buffer_size):
        return self._SOCKET.recv(buffer_size).decode('utf-8', 'ignore')

    # def recvall(self, buffer_size):
    #     fragments = []  # faster than byte string
    #     while True:
    #         part = self._SOCKET.recv(buffer_size)
    #         fragments.append(part)

    #         # attempt to decode this, otherwise the last byte was incomplete
    #         # in this case, get more data
    #         try:
    #             # if len(part) < buffer_size:
    #             return b''.join(fragments).decode('utf-8') # , 'ignore'
    #         except UnicodeDecodeError:
    #             # print('error', data)
    #             continue

    def join_channel(self, channel_name):
        channel_lower = channel_name.lower()

        if self._CURRENT_CHANNEL != channel_lower:
            self.send_raw('JOIN #{}'.format(channel_lower))
            self._CURRENT_CHANNEL = channel_lower

    def set_timeout(self, message_receive_timeout):
        self._SOCKET.settimeout(message_receive_timeout)

    def close_connection(self):
        self._SOCKET.close()

        # except KeyboardInterrupt:
        # 	print('Interrupted by user.')

        # except Exception as e:
        # 	print('Unknown Error:',e)
        # 	raise e

        # return messages


class TwitchChatDownloader(ChatDownloader):
    _BADGE_INFO = {}
    _BADGE_INFO_URL = 'https://badges.twitch.tv/v1/badges/global/display'
    # TODO add local version of badge list?

    def __init__(self, updated_init_params=None):
        super().__init__(updated_init_params or {})
        # self._name = None
        # self.name = 'Twitch.tv'

        TwitchChatDownloader._BADGE_INFO = self._session_get_json(
            self._BADGE_INFO_URL).get('badge_sets') or {}
        # print(TwitchChatDownloader._BADGE_INFO.keys(), flush=True)
        # #exit()
        # # print(TwitchChatDownloader._BADGE_INFO)
        #

    _DEFAULT_FORMAT = 'twitch'

    def __str__(self):
        return 'Twitch.tv'

    _TESTS = [
        # Commenter is "None"
        # https://www.twitch.tv/videos/873616984 --start_time 1:26:10
    ]

    # clips
    # vod
    # name -> live

    _VALID_URL = r'https?://(?:(?:www|go|m|clips)\.)?twitch\.tv'

    # e.g. 'http://www.twitch.tv/riotgames/v/6528877?t=5m10s'
    _VALID_VOD_URL = r'''(?x)
                    https?://
                        (?:
                            (?:(?:www|go|m)\.)?twitch\.tv/(?:[^/]+/v(?:ideo)?|videos)/|
                            player\.twitch\.tv/\?.*?\bvideo=v?
                        )
                        (?P<id>\d+)
                    '''

    # e.g. 'https://clips.twitch.tv/FaintLightGullWholeWheat'
    _VALID_CLIPS_URL = r'''(?x)
                        https?://
                            (?:
                                clips\.twitch\.tv/(?:embed\?.*?\bclip=|(?:[^/]+/)*)|
                                (?:(?:www|go|m)\.)?twitch\.tv/[^/]+/clip/
                            )
                            (?P<id>[^/?#&]+)
                        '''

    # e.g. 'http://www.twitch.tv/shroomztv'
    _VALID_STREAM_URL = r'''(?x)
                        https?://
                            (?:
                                (?:(?:www|go|m)\.)?twitch\.tv/|
                                player\.twitch\.tv/\?.*?\bchannel=
                            )
                            (?P<id>[^/#?]+)
                        '''

    _CLIENT_ID = 'kimne78kx3ncx6brgo4mv6wki5h1ko'  # public client id

    _GQL_API_URL = 'https://gql.twitch.tv/gql'
    _API_TEMPLATE = 'https://api.twitch.tv/v5/videos/{}/comments?client_id={}'

    _PING_TEXT = 'PING :tmi.twitch.tv'
    _PONG_TEXT = 'PONG :tmi.twitch.tv'

    _SUBSCRIPTION_TYPES = {
        'Prime': 'Prime',
        '1000': 'Tier 1',
        '2000': 'Tier 2',
        '3000': 'Tier 3'
    }

    _REMAP_FUNCTIONS = {
        'parse_timestamp': timestamp_to_microseconds,  # lambda x :  * 1000,
        'parse_author_images': lambda x: TwitchChatDownloader.parse_author_images(x),

        'parse_badges': lambda x: TwitchChatDownloader.parse_badges(x),

        'multiply_by_1000': lambda x: int_or_none(x) * 1000,
        'parse_int': int_or_none,
        'parse_bool': lambda x: x == '1',
        'parse_bool_text': lambda x: x == 'true',

        'replace_with_underscores': replace_with_underscores,


        'parse_subscription_type': lambda x: TwitchChatDownloader._SUBSCRIPTION_TYPES.get(x),
        'parse_commenter': lambda x: TwitchChatDownloader.parse_commenter(x),
        'parse_message_info': lambda x: TwitchChatDownloader.parse_message_info(x),

        'decode_pseudo_BNF': lambda x: TwitchChatDownloader.decode_pseudo_BNF(x)
    }
    _AUTHOR_REMAPPING = {
        '_id': ('id', 'parse_int'),
        'name': 'name',
        'display_name': 'display_name',
        'logo': ('images', 'parse_author_images'),
        'type': 'type',
        'created_at': ('created_at', 'parse_timestamp'),
        # 'updated_at': ('updated_at', 'parse_timestamp'),
        'bio': 'bio'

    }
    #
    _COMMENT_REMAPPING = {
        '_id': 'message_id',
        'created_at': ('timestamp', 'parse_timestamp'),
        'commenter': ('author', 'parse_commenter'),

        'content_offset_seconds': 'time_in_seconds',

        'source': 'source',
        'state': 'state',
        # TODO make sure body vs. fragments okay
        'message': ('message_info', 'parse_message_info')
    }

    _MESSAGE_PARAM_REMAPPING = {
        'msg-id': 'message_type',

        'msg-param-cumulative-months': ('cumulative_months', 'parse_int'),
        'msg-param-months': ('months', 'parse_int'),
        'msg-param-displayName': 'raider_display_name',
        'msg-param-login': 'raider_name',
        'msg-param-viewerCount': ('number_of_raiders', 'parse_int'),

        'msg-param-promo-name': 'promotion_name',
        'msg-param-promo-gift-total': 'number_of_gifts_given_during_promo',

        'msg-param-recipient-id': 'gift_recipient_id',
        'msg-param-recipient-user-name': 'gift_recipient_display_name',
        'msg-param-recipient-display-name': 'gift_recipient_display_name',
        'msg-param-gift-months': ('number_of_months_gifted', 'parse_int'),


        'msg-param-sender-login': 'gifter_name',
        'msg-param-sender-name': 'gifter_display_name',

        'msg-param-should-share-streak': ('user_wants_to_share_streaks', 'parse_bool'),
        'msg-param-streak-months': ('number_of_consecutive_months_subscribed', 'parse_int'),
        'msg-param-sub-plan': ('subscription_type', 'parse_subscription_type'),
        'msg-param-sub-plan-name': 'subscription_plan_name',

        'msg-param-ritual-name': 'ritual_name',

        'msg-param-threshold': 'bits_badge_tier',


        # found in vods

        # resub
        'msg-param-multimonth-duration': ('multimonth_duration', 'parse_int'),
        'msg-param-multimonth-tenure': ('multimonth_tenure', 'parse_int'),
        'msg-param-was-gifted': ('was_gifted', 'parse_bool_text'),

        'msg-param-gifter-id': 'gifter_id',
        'msg-param-gifter-login': 'gifter_name',
        'msg-param-gifter-name': 'gifter_display_name',
        'msg-param-anon-gift': ('was_anonymous_gift', 'parse_bool_text'),
        'msg-param-gift-month-being-redeemed': ('gift_months_being_redeemed', 'parse_int'),

        # rewardgift
        'msg-param-domain': 'domain',
        'msg-param-selected-count': ('selected_count', 'parse_int'),
        'msg-param-trigger-type': 'trigger_type',
        'msg-param-total-reward-count': ('total_reward_count', 'parse_int'),
        'msg-param-trigger-amount': ('trigger_amount', 'parse_int'),

        # submysterygift
        'msg-param-origin-id': 'origin_id',
        'msg-param-sender-count': ('sender_count', 'parse_int'),
        'msg-param-mass-gift-count': ('mass_gift_count', 'parse_int'),

        # communitypayforward
        'msg-param-prior-gifter-anonymous': ('prior_gifter_anonymous', 'parse_bool_text'),
        'msg-param-prior-gifter-user-name': 'prior_gifter_name',
        'msg-param-prior-gifter-display-name': 'prior_gifter_display_name',
        'msg-param-prior-gifter-id': 'prior_gifter_id',

        'msg-param-fun-string': 'fun_string',

        # not come across yet, but other tools have it:
        # 'msg-param-charity':'charity',
        # 'msg-param-bits-amount':'bits_amount',
        # 'msg-param-total':'total',
        # 'msg-param-streak-tenure-months':'streak_tenure_months',
        # 'msg-param-sub-benefit-end-month':'sub_benefit_end_month',
        # 'msg-param-userID':'user_id',
        #
        # 'msg-param-cumulative-tenure-months':'cumulative_tenure_months',
        # 'msg-param-should-share-streak-tenure':'should-share-streak-tenure',
        # 'msg-param-min-cheer-amount' :'minimum_cheer_amount',
        # 'msg-param-gift-name':'gift_name',

        # 'msg-param-charity-hashtag':'charity_hashtag',
        # 'msg-param-charity-hours-remaining':'charity_hours_remaining',
        # 'msg-param-charity-days-remaining':'charity_days_remaining',
        # 'msg-param-charity-name':'charity_name',
        # 'msg-param-charity-learn-more':'charity_learn_more',


        # to remove later
        'msg-param-profileImageURL': 'profile_image_url'
    }

    # Create set of known types
    _KNOWN_COMMENT_KEYS = {
        # created elsewhere
        'message', 'time_in_seconds', 'message_id', 'time_text', 'author', 'timestamp', 'message_type'
    }

    _KNOWN_COMMENT_KEYS.update(ChatDownloader.get_mapped_keys({
        **_COMMENT_REMAPPING, **_MESSAGE_PARAM_REMAPPING
    }))
    # print('_KNOWN_COMMENT_KEYS',_KNOWN_COMMENT_KEYS)

    _IRC_REMAPPING = {
        # CLEARCHAT
        # Purges all chat messages in a channel, or purges chat messages from a specific user, typically after a timeout or ban.
        # (Optional) Duration of the timeout, in seconds. If omitted, the ban is permanent.
        'ban-duration': ('ban_duration', 'parse_int'),

        # CLEARMSG
        # Removes a single message from a channel. This is triggered by the/delete <target-msg-id> command on IRC.
        # Name of the user who sent the message.
        'login': 'author_name',
        # UUID of the message.
        'target-msg-id': 'target_message_id',


        # GLOBALUSERSTATE
        # On successful login, provides data about the current logged-in user through IRC tags. It is sent after successfully authenticating (sending a PASS/NICK command).

        'emote-sets': 'emote_sets',  # TODO split by,?

        # GENERAL
        # can be empty (which means it depends on dark/light theme)
        'color': 'colour',
        'display-name': 'author_display_name',
        'user-id': ('author_id', 'parse_int'),



        # reply-parent-display-name


        # PRIVMSG
        'badge-info': ('author_badge_metadata', 'parse_badges'),
        'badges': ('author_badges', 'parse_badges'),

        'bits': ('bits', 'parse_int'),

        'id': 'message_id',
        'mod': ('is_moderator', 'parse_bool'),
        'room-id': ('channel_id', 'parse_int'),

        'tmi-sent-ts': ('timestamp', 'multiply_by_1000'),

        'subscriber': ('is_subscriber', 'parse_bool'),
        'turbo': ('is_turbo', 'parse_bool'),

        'client-nonce': 'client_nonce',

        'user-type': 'user_type',



        'reply-parent-msg-body': ('in_reply_to_message', 'decode_pseudo_BNF'),
        'reply-parent-user-id': ('in_reply_to_author_id', 'parse_int'),
        'reply-parent-msg-id': 'in_reply_to_message_id',
        'reply-parent-display-name': 'in_reply_to_author_display_name',
        'reply-parent-user-login': 'in_reply_to_author_name',


        'custom-reward-id': 'custom_reward_id',


        # Information to replace text in the message with emote images. This can be empty.
        # <emote ID>:<first index>-<last index>,<another first index>-<another last index>/<another emote ID>:<first index>-<last index>
        # TODO parse emote info?
        'emotes': 'emotes',
        'flags': 'flags',



        # ROOMSTATE
        'emote-only': ('emote_only', 'parse_bool'),
        'followers-only': ('follower_only', 'parse_int'),

        'r9k': ('r9k_mode', 'parse_bool'),
        'slow': ('slow_mode', 'parse_int'),
        'subs-only': ('subscriber_only', 'parse_bool'),
        'rituals': ('rituals_enabled', 'parse_bool'),

        # USERNOTICE
        'system-msg': 'system_message',

        # (Commands)
        # HOSTTARGET
        'number-of-viewers': 'number_of_viewers',

        # ban user
        'target-user-id': ('target_author_id', 'parse_int'),

        # USERNOTICE - other
        **_MESSAGE_PARAM_REMAPPING
    }

    _KNOWN_IRC_KEYS = {
        # banned user
        'banned_user', 'ban_type',

        # slow mode
        'seconds_to_wait',

        # follower only
        'minutes_to_follow_before_chatting',

        # parsed elsewhere
        'action_type',
        'author',
        'in_reply_to',
        'message'
    }
    _KNOWN_IRC_KEYS.update(ChatDownloader.get_mapped_keys(_IRC_REMAPPING))

    _ACTION_TYPE_REMAPPING = {
        # tags
        'CLEARCHAT': 'clear_chat',
        'CLEARMSG': 'delete_message',
        'GLOBALUSERSTATE': 'successful_login',
        'PRIVMSG': 'text_message',
        'ROOMSTATE': 'room_state',
        'USERNOTICE': 'user_notice',
        'USERSTATE': 'user_state',

        # commands
        'HOSTTARGET': 'host_target',
        'NOTICE': 'notice',
        'RECONNECT': 'reconnect'
    }

    # msg-id's
    _MESSAGE_GROUP_REMAPPINGS = {
        # TODO add rest of
        # https://dev.twitch.tv/docs/irc/msg-id

        'messages': {
            'highlighted-message': 'highlighted_message',
            'skip-subs-mode-message': 'send_message_in_subscriber_only_mode',
        },
        'bits': {
            'bitsbadgetier': 'bits_badge_tier',
        },
        'subscriptions': {
            'sub': 'subscription',
            'resub': 'resubscription',
            'subgift': 'subscription_gift',
            'anonsubgift': 'anonymous_subscription_gift',
            'anonsubmysterygift': 'anonymous_mystery_subscription_gift',
            'submysterygift': 'mystery_subscription_gift',
            'extendsub': 'extend_subscription',

            'standardpayforward': 'standard_pay_forward',
            'communitypayforward': 'community_pay_forward',
            'primecommunitygiftreceived': 'prime_community_gift_received',
        },
        'upgrades': {
            'primepaidupgrade': 'prime_paid_upgrade',
            'giftpaidupgrade': 'gift_paid_upgrade',
            'rewardgift': 'reward_gift',
            'anongiftpaidupgrade': 'anonymous_gift_paid_upgrade',
        },
        'raids': {
            'raid': 'raid',
            'unraid': 'unraid'
        },
        'hosts': {
            'host_on': 'start_host',
            'host_off': 'end_host',
            'bad_host_hosting': 'bad_host_hosting',
            'bad_host_rate_exceeded': 'bad_host_rate_exceeded',
            'bad_host_error': 'bad_host_error',
            'hosts_remaining': 'hosts_remaining',
            'not_hosting': 'not_hosting',

            'host_target_went_offline': 'host_target_went_offline',
        },
        'rituals': {
            'ritual': 'ritual',
        },
        'room_states': {
            # slow mode
            'slow_on': 'enable_slow_mode',
            'slow_off': 'disable_slow_mode',
            'already_slow_on': 'slow_mode_already_on',
            'already_slow_off': 'slow_mode_already_off',

            # sub only mode
            'subs_on': 'enable_subscriber_only_mode',
            'subs_off': 'disable_subscriber_only_mode',
            'already_subs_on': 'sub_mode_already_on',
            'already_subs_off': 'sub_mode_already_off',

            # emote only mode
            'emote_only_on': 'enable_emote_only_mode',
            'emote_only_off': 'disable_emote_only_mode',
            'already_emote_only_on': 'emote_only_already_on',
            'already_emote_only_off': 'emote_only_already_off',

            # r9k mode
            'r9k_on': 'enable_r9k_mode',
            'r9k_off': 'disable_r9k_mode',
            'already_r9k_on': 'r9k_mode_already_on',
            'already_r9k_off': 'r9k_mode_already_off',

            # follower only mode
            'followers_on': 'enable_follower_only_mode',
            'followers_on_zero': 'enable_follower_only_mode',  # same thing, handled in parse
            'followers_off': 'disable_follower_only_mode',
            'already_followers_on': 'follower_only_mode_already_on',
            'already_followers_on_zero': 'follower_only_mode_already_on',
            'already_followers_off': 'follower_only_mode_already_off',

        },
        'deleted_messages': {
            'msg_banned': 'banned_message',

            'bad_delete_message_error': 'bad_delete_message_error',
            'bad_delete_message_broadcaster': 'bad_delete_message_broadcaster',
            'bad_delete_message_mod': 'bad_delete_message_mod',
            'delete_message_success': 'delete_message_success',
        },
        'bans': {

            # ban
            'already_banned': 'already_banned',
            'bad_ban_self': 'bad_ban_self',
            'bad_ban_broadcaster': 'bad_ban_broadcaster',
            'bad_ban_admin': 'bad_ban_admin',
            'bad_ban_global_mod': 'bad_ban_global_mod',
            'bad_ban_staff': 'bad_ban_staff',
            'ban_success': 'ban_success',

            # unban
            'bad_unban_no_ban': 'bad_unban_no_ban',
            'unban_success': 'unban_success',

            'msg_channel_suspended': 'channel_suspended_message',

            # timeouts
            'timeout_success': 'timeout_success',

            # timeout errors
            'bad_timeout_self': 'bad_timeout_self',
            'bad_timeout_broadcaster': 'bad_timeout_broadcaster',
            'bad_timeout_mod': 'bad_timeout_mod',
            'bad_timeout_admin': 'bad_timeout_admin',
            'bad_timeout_global_mod': 'bad_timeout_global_mod',
            'bad_timeout_staff': 'bad_timeout_staff',
        },
        'mods': {
            'bad_mod_banned': 'bad_mod_banned',
            'bad_mod_mod': 'bad_mod_mod',
            'mod_success': 'mod_success',
            'bad_unmod_mod': 'bad_unmod_mod',
            'unmod_success': 'unmod_success',
            'no_mods': 'no_mods',
            'room_mods': 'room_mods',
        },
        'colours': {
            'turbo_only_color': 'turbo_only_colour',
            'color_changed': 'colour_changed',
        },
        'commercials': {
            'bad_commercial_error': 'bad_commercial_error',
            'commercial_success': 'commercial_success',
        },

        'vips': {
            'bad_vip_grantee_banned': 'bad_vip_grantee_banned',
            'bad_vip_grantee_already_vip': 'bad_vip_grantee_already_vip',
            'vip_success': 'vip_success',
            'bad_unvip_grantee_not_vip': 'bad_unvip_grantee_not_vip',
            'unvip_success': 'unvip_success',
            'no_vips': 'no_vips',
            'vips_success': 'vips_success',
        },
        'other': {
            'cmds_available': 'cmds_available',
            'unrecognized_cmd': 'unrecognized_cmd',
            'no_permission': 'no_permission',
            'msg_ratelimit': 'rate_limit_reached_message',
        }
    }

    _MESSAGE_GROUPS = {
        'messages': [
            'text_message'
        ],
        'bans': [
            'ban_user'
        ],
        'deleted_messages': [
            'delete_message'
        ],
        'hosts': [
            'host_target'
        ],
        'room_states': [
            'room_state'
        ],
        'user_states': [
            'user_state'
        ],
        'notices': [
            'user_notice',
            'notice',
            'successful_login'
        ],
        'other': [
            'clear_chat',
            'reconnect'
        ]
    }

    _MESSAGE_TYPE_REMAPPING = {}
    for message_group in _MESSAGE_GROUP_REMAPPINGS:
        value = _MESSAGE_GROUP_REMAPPINGS[message_group]
        _MESSAGE_TYPE_REMAPPING.update(value)

        if message_group not in _MESSAGE_GROUPS:
            _MESSAGE_GROUPS[message_group] = []
        _MESSAGE_GROUPS[message_group] += list(value.values())

    @staticmethod
    def parse_author_images(original_url):
        smaller_icon = original_url.replace('300x300', '70x70')
        return [
            ChatDownloader.create_image(original_url, 300, 300),
            ChatDownloader.create_image(smaller_icon, 70, 70),
        ]

    @ staticmethod
    def _parse_item(item, offset):
        # if params is None:
        #     params = {}

        info = {}
        for key in item:
            ChatDownloader.remap(info, TwitchChatDownloader._COMMENT_REMAPPING,
                                 TwitchChatDownloader._REMAP_FUNCTIONS, key, item[key])  # , True

        if 'time_in_seconds' in info:
            info['time_in_seconds'] -= offset
            info['time_text'] = seconds_to_time(int(info['time_in_seconds']))

        message_info = info.pop('message_info', None)
        if message_info:
            info['message'] = message_info.get('message')
            info['author']['colour'] = message_info.get('colour')

            badges = message_info.get('badges')
            if badges:
                info['author']['badges'] = badges

        user_notice_params = message_info.pop('user_notice_params', {})

        for key in user_notice_params:
            ChatDownloader.remap(info, TwitchChatDownloader._MESSAGE_PARAM_REMAPPING,
                                 TwitchChatDownloader._REMAP_FUNCTIONS, key, user_notice_params[key], True)

        original_message_type = info.get('message_type')
        if original_message_type:
            TwitchChatDownloader._set_message_type(info, original_message_type)
        else:
            info['message_type'] = 'text_message'

        # remove profile_image_url if present
        info.pop('profile_image_url', None)

        return info

    _OPERATION_HASHES = {
        'StreamMetadata': '1c719a40e481453e5c48d9bb585d971b8b372f8ebb105b17076722264dfa5b3e',
        'BrowsePage_Popular': 'c3322a9df3121f437182beb5a75c2a8db9a1e27fa57701ffcae70e681f502557',
        'ChannelVideoShelvesQuery': 'fb663273aa958ebe2f58d5fcb3aacc112d67ebfd7f414b095c5d1498d21aad92',
        'ClipsCards__User': 'b73ad2bfaecfd30a9e6c28fada15bd97032c83ec77a0440766a56fe0bd632777',
        'VideoMetadata': '226edb3e692509f727fd56821f5653c05740242c82b0388883e0c0e75dcbf687',

        # Not used yet
        # 'CollectionSideBar': '27111f1b382effad0b6def325caef1909c733fe6a4fbabf54f8d491ef2cf2f14',
        # 'FilterableVideoTower_Videos': 'a937f1d22e269e39a03b509f65a7490f9fc247d7f83d6ac1421523e3b68042cb',
        # 'ChannelCollectionsContent': '07e3691a1bad77a36aba590c351180439a40baefc1c275356f40fc7082419a84',
        # 'ComscoreStreamingQuery': 'e1edae8122517d013405f237ffcc124515dc6ded82480a88daef69c83b53ac01',
        # 'VideoPreviewOverlay': '3006e77e51b128d838fa4e835723ca4dc9a05c5efd4466c1085215c6e437e65c',
    }

    def _download_base_gql(self, ops):
        return self._session_post(self._GQL_API_URL, data=json.dumps(ops).encode(), headers={
            'Content-Type': 'text/plain;charset=UTF-8',
            'Client-ID': self._CLIENT_ID
        }).json()

    def _download_gql(self, ops):
        for op in ops:
            op['extensions'] = {
                'persistedQuery': {
                    'version': 1,
                    'sha256Hash': self._OPERATION_HASHES[op['operationName']],
                }
            }
        return self._download_base_gql(ops)

    def get_user_clips(self, user_name, limit=100, filter_by='LAST_WEEK'):

        # filter_by:
        # LAST_WEEK
        # LAST_DAY
        # LAST_MONTH
        # ALL_TIME

        # offset= 20# , offset = 0

        count = limit
        offset = 0
        to_return = []
        while True:
            cursor = base64.b64encode(str(offset).encode()).decode()
            num_to_get = max(min(count, 100), 0)
            if num_to_get <= 0:
                break
            # print('num_to_get', num_to_get)

            query = [{
                'operationName': 'ClipsCards__User',
                'variables':
                {
                    'cursor': cursor,
                    'login': user_name,
                    'limit': num_to_get,
                    'criteria':
                    {
                        'filter': filter_by
                    }
                }
            }]
            info = self._download_gql(query)
            if not info:
                break
            clips = info[0]['data']['user']['clips']

            edges = clips['edges']

            count -= len(edges)

            to_return += edges

            if not clips['pageInfo']['hasNextPage']:
                break

        return to_return

        # TODO check if pageInfo hasNextPage

        # print(len(edges))
        return edges

    def get_user_vods(self, user_name):
        query = [{
            'operationName': 'ChannelVideoShelvesQuery',
            'variables': {
                'channelLogin': user_name,
                'first': 5
            }
        }]
        edges = self._download_gql(
            query)[0]['data']['user']['videoShelves']['edges']
        # print(len(edges))
        return edges

    def get_top_livestreams(self, limit=30):
        count = limit

        cursor = ''

        to_return = []
        while True:
            num_to_get = max(min(count, 30), 0)
            if num_to_get <= 0:
                break
            # print('num_to_get', num_to_get)

            query = [{
                'operationName': 'BrowsePage_Popular',
                'variables': {
                    'limit': num_to_get,
                    'cursor': cursor,
                    'platformType': 'all',
                    'options': {
                        'sort': 'VIEWER_COUNT'  # RECENT, RELEVANCE, VIEWER_COUNT_ASC
                    },
                    'sortTypeIsRecency': False
                }
            }]
            edges = self._download_gql(query)[0]['data']['streams']['edges']

            cursor = edges[-1]['cursor']
            count -= num_to_get

            to_return += edges

        return to_return
        # print(streams)

    _REGEX_FUNCTION_MAP = [
        (_VALID_VOD_URL, 'get_chat_by_vod_id'),
        (_VALID_CLIPS_URL, 'get_chat_by_clip_id'),
        (_VALID_STREAM_URL, 'get_chat_by_stream_id'),
    ]

    # offset and max_duration are used by clips
    def _get_chat_messages_by_vod_id(self, vod_id, params, offset=0, max_duration=None):

        # twitch does not provide messages before the stream starts,
        # so we default to a start time of 0
        start_time = ensure_seconds(
            self.get_param_value(params, 'start_time'), 0)
        end_time = ensure_seconds(
            self.get_param_value(params, 'end_time'), max_duration)

        max_attempts = self.get_param_value(params, 'max_attempts')
        retry_timeout = self.get_param_value(params, 'retry_timeout')

        messages_groups_to_add = self.get_param_value(
            params, 'message_groups') or []
        messages_types_to_add = self.get_param_value(
            params, 'message_types') or []

        pause_on_debug = self.get_param_value(params, 'pause_on_debug')

        def debug_log(*items):
            log(
                'debug',
                items,
                pause_on_debug
            )
        # TODO Remove this and make same as IRC
        # invalid_message_groups = all(
        #     key not in messages_groups_to_add for key in ('all', 'messages'))
        # invalid_message_types = messages_types_to_add and 'text_message' not in messages_types_to_add

        # if invalid_message_groups or invalid_message_types:
        #     raise InvalidParameter(
        #         'Custom method types/groups are not supported for Twitch VODs/clips')

        api_url = self._API_TEMPLATE.format(vod_id, self._CLIENT_ID)

        content_offset_seconds = (start_time or 0) + offset

        timeout = Timeout(self.get_param_value(params, 'timeout'))
        cursor = ''
        while True:
            url = '{}&cursor={}&content_offset_seconds={}'.format(
                api_url, cursor, content_offset_seconds)

            for attempt_number in attempts(max_attempts):
                timeout.check_for_timeout()
                try:
                    info = self._session_get_json(url)
                    break
                except (UnexpectedHTML, RequestException) as e:
                    self.retry(attempt_number, max_attempts, e, retry_timeout)

            error = info.get('error')

            if error:
                # TODO make parse error and raise more general errors
                raise TwitchError(info.get('message'))

            comments = info.get('comments') or []
            for comment in comments:
                data = self._parse_item(comment, offset)

                # test for missing keys
                missing_keys = data.keys()-TwitchChatDownloader._KNOWN_COMMENT_KEYS

                if missing_keys:
                    debug_log(
                        'Missing keys found: {}'.format(missing_keys),
                        'Original data: {}'.format(comment),
                        'Parsed data: {}'.format(data),
                        comment.keys(),
                        TwitchChatDownloader._KNOWN_COMMENT_KEYS
                    )

                time_in_seconds = data.get('time_in_seconds', 0)

                before_start = start_time is not None and time_in_seconds < start_time
                after_end = end_time is not None and time_in_seconds > end_time

                if before_start:  # still getting to messages
                    continue
                elif after_end:  # after end
                    return  # while actually searching, if time is invalid

                to_add = self.must_add_item(
                    data,
                    self._MESSAGE_GROUPS,
                    messages_groups_to_add,
                    messages_types_to_add
                )

                if not to_add:
                    continue

                yield data

            cursor = info.get('_next')

            if not cursor:
                return

    def get_chat_by_vod_id(self, vod_id, params):
        max_attempts = self.get_param_value(params, 'max_attempts')
        retry_timeout = self.get_param_value(params, 'retry_timeout')


        query = [{
            'operationName': 'VideoMetadata',
            'variables': {
                'channelLogin': '',
                'videoID': vod_id
            }
        }]


        pause_on_debug = self.get_param_value(params, 'pause_on_debug')

        for attempt_number in attempts(max_attempts):
            try:
                video = self._download_gql(query)[0]['data']['video']
                break
            except (UnexpectedHTML, RequestException) as e:
                self.retry(attempt_number, max_attempts, e, retry_timeout)

        title = video.get('title')
        duration = video.get('lengthSeconds')

        return Chat(
            self,
            self._get_chat_messages_by_vod_id(
                vod_id, params),
            title=title,
            duration=duration,
            is_live=False
        )

    def get_chat_by_clip_id(self, clip_id, params):

        max_attempts = self.get_param_value(params, 'max_attempts')
        retry_timeout = self.get_param_value(params, 'retry_timeout')


        query = {
            'query': '{ clip(slug: "%s") { video { id createdAt } createdAt durationSeconds videoOffsetSeconds title url slug } }' % clip_id,
        }
        pause_on_debug = self.get_param_value(params, 'pause_on_debug')

        for attempt_number in attempts(max_attempts):
            try:
                clip = self._download_base_gql(query)['data']['clip']
                break
            except (UnexpectedHTML, RequestException) as e:
                self.retry(attempt_number, max_attempts, e, retry_timeout)

        vod_id = multi_get(clip, 'video', 'id')
        if vod_id is None:
            raise NoChatReplay(
                'Video does not have a chat replay. This is because the original VOD has been deleted.')

        offset = clip.get('videoOffsetSeconds')

        duration = clip.get('durationSeconds')
        title = '{} ({})'.format(clip.get('title'), clip_id)

        return Chat(
            self,
            self._get_chat_messages_by_vod_id(
                vod_id, params, offset, duration),
            title=title,
            duration=duration,
            is_live=False
        )

    # e.g. @badge-info=;badges=;client-nonce=c5fbf6b9f6b249353811c21dfffe0321;color=#FF69B4;display-name=sumz5;emotes=;flags=;id=340fec40-f54c-4393-a044-bf62c636e98b;mod=0;room-id=86061418;subscriber=0;tmi-sent-ts=1607447245754;turbo=0;user-id=611966876;user-type= :sumz5!sumz5@sumz5.tmi.twitch.tv PRIVMSG #5uppp :PROXIMITY?

    _MESSAGE_REGEX = re.compile(
        r'^@(.+?(?=\s+:)).*tmi\.twitch\.tv\s+(\S+)(?:.+#\S+)?(?:.:)*([^\r\n]*)', re.MULTILINE)
    # Groups:
    # 1. Tag info
    # 2. Action type
    # 3. Message

    # A full list can be found here: https://badges.twitch.tv/v1/badges/global/display

    _BADGE_KEYS = ('title', 'description', 'image_url_1x',
                   'image_url_2x', 'image_url_4x', 'click_action', 'click_url')
    _BADGE_ID_REGEX = r'v1/(.+)/'

    @staticmethod
    def parse_badge_info(name, version, set_subscriber_badge_info=False):
        new_badge = {
            'name': replace_with_underscores(name),
            'version': int_or_none(version, version)
        }
        if name == 'subscriber':
            if set_subscriber_badge_info:
                TwitchChatDownloader._set_subscriber_badge_info(
                    new_badge, version)
        else:  # is global emote
            new_badge_info = multi_get(
                TwitchChatDownloader._BADGE_INFO, name, 'versions', version) or {}

            if new_badge_info:
                for key in TwitchChatDownloader._BADGE_KEYS:
                    new_badge[key] = new_badge_info.get(key)

                image_urls = [
                    (new_badge.pop('image_url_{}x'.format(i), ''), i*18) for i in (1, 2, 4)]
                if image_urls:
                    new_badge['icons'] = []

                for image_url, size in image_urls:
                    new_badge['icons'].append(
                        ChatDownloader.create_image(image_url, size, size))

                if image_urls:
                    badge_id = re.search(
                        TwitchChatDownloader._BADGE_ID_REGEX, image_urls[0][0] or '')
                    if badge_id:
                        new_badge['id'] = badge_id.group(1)

        return new_badge

    @staticmethod
    def parse_badges(badges):
        info = []
        if not badges:
            return info

        for badge in badges.split(','):
            split = badge.split('/', 1)
            key_length = len(split)
            if key_length == 1:
                # If there's no /, we assign a value of None (null).
                split.append(None)
            elif key_length == 2:
                pass
            else:
                print('INVALID BADGE FOUND')
                print(badge)
                print(badges)
                input()
                continue  # TODO debug

            info.append(TwitchChatDownloader.parse_badge_info(
                split[0], split[1]))
        return info

    @staticmethod
    def parse_commenter(commenter):
        info = {}
        for key in commenter or []:
            ChatDownloader.remap(info, TwitchChatDownloader._AUTHOR_REMAPPING,
                                 TwitchChatDownloader._REMAP_FUNCTIONS, key, commenter[key])
        return info

    @staticmethod
    def parse_message_info(message):
        return {
            'message': message.get('body'),
            'colour': message.get('user_color'),
            'badges': list(map(
                lambda x: TwitchChatDownloader.parse_badge_info(
                    x.get('_id'), x.get('version'), True), message.get('user_badges') or [])),
            'user_notice_params': message.get('user_notice_params')
        }

    @staticmethod
    def decode_pseudo_BNF(text):
        """
        Decode text according to https://ircv3.net/specs/extensions/message-tags.html
        """
        return text.replace('\:', ';').replace('\s', ' ')

    # print(_MESSAGE_TYPE_REMAPPING)
    @staticmethod
    def _set_subscriber_badge_info(badge, months):
        num_months = int(months)
        title = 'Subscriber'
        if num_months:
            badge['months'] = num_months
            title = '{}-Month {}'.format(months, title)

        badge['title'] = badge['description'] = title

    @staticmethod
    def _set_message_type(info, original_message_type, params=None):
        if params is None:
            params = {}
        new_message_type = TwitchChatDownloader._MESSAGE_TYPE_REMAPPING.get(
            original_message_type)

        #print(original_message_type, '-->', new_message_type)

        if new_message_type:
            info['message_type'] = new_message_type
        else:
            log(
                'debug',
                'Unknown message type:', original_message_type,
                params.get('pause_on_debug')
            )

    @staticmethod
    def _parse_irc_item(match):
        info = {}

        split_info = match.group(1).split(';')

        for item in split_info:
            keys = item.split('=', 1)
            key_length = len(keys)
            if key_length == 1:
                # If there's no equals, we assign the tag a value of true.
                keys.append(True)
            elif key_length == 2:
                pass
            else:
                print('INVALID ITEM FOUND')
                print(split_info)
                input()  # TODO debug
                continue

            ChatDownloader.remap(info, TwitchChatDownloader._IRC_REMAPPING,
                                 TwitchChatDownloader._REMAP_FUNCTIONS, keys[0], keys[1],
                                 keep_unknown_keys=True,
                                 replace_char_with_underscores='-')

        message_match = match.group(3)
        if message_match:
            info['message'] = remove_prefixes(message_match, '\u0001ACTION ')

        badge_metadata = info.pop('author_badge_metadata', [])
        badge_info = info.get('author_badges', [])

        subscriber_badge = next(
            (x for x in badge_info if x.get('name') == 'subscriber'), None)
        subscriber_badge_metadata = next(
            (x for x in badge_metadata if x.get('name') == 'subscriber'), None)
        if subscriber_badge and subscriber_badge_metadata:
            TwitchChatDownloader._set_subscriber_badge_info(subscriber_badge,
                                                            subscriber_badge_metadata['version'])

        author_display_name = info.get('author_display_name')
        if author_display_name:
            info['author_name'] = author_display_name.lower()

        in_reply_to = ChatDownloader.move_to_dict(info, 'in_reply_to')

        ChatDownloader.move_to_dict(in_reply_to, 'author')
        # ChatDownloader.move_to_dict(info['in_reply_to'], 'author')
        ChatDownloader.move_to_dict(info, 'author')

        original_action_type = match.group(2)

        if original_action_type:
            new_action_type = TwitchChatDownloader._ACTION_TYPE_REMAPPING.get(
                original_action_type)
            if new_action_type:
                info['action_type'] = new_action_type
            else:
                # unknown action type
                info['action_type'] = original_action_type

        original_message_type = info.get('message_type')
        if original_message_type:
            TwitchChatDownloader._set_message_type(info, original_message_type)
        else:
            info['message_type'] = info['action_type']

        if original_action_type == 'CLEARCHAT':
            if message_match:  # is a ban
                info['message_type'] = 'ban_user'
                info['ban_type'] = 'timeout' if info.get(
                    'ban_duration') else 'permanent'
                info['banned_user'] = info.pop('message', '')

            else:  # did /clearchat
                pass

        follower_only = info.get('follower_only')
        if follower_only:
            info['follower_only'] = follower_only != -1
            if follower_only > 0:
                info['minutes_to_follow_before_chatting'] = follower_only

        slow_mode = info.get('slow_mode')
        if slow_mode is not None:
            if slow_mode != 0:
                info['slow_mode'] = True
                info['seconds_to_wait'] = slow_mode
            else:
                info['slow_mode'] = False

        # TODO
        # :tmi.twitch.tv HOSTTARGET #gothamchess :anna_chess 6612
        return info

    def _get_chat_messages_by_stream_id(self, stream_id, params):
        max_attempts = self.get_param_value(params, 'max_attempts')
        retry_timeout = self.get_param_value(params, 'retry_timeout')


        message_receive_timeout = self.get_param_value(
            params, 'message_receive_timeout')
        timeout = self.get_param_value(params, 'timeout')

        buffer_size = self.get_param_value(params, 'buffer_size')

        messages_groups_to_add = self.get_param_value(
            params, 'message_groups') or []
        messages_types_to_add = self.get_param_value(
            params, 'message_types') or []

        pause_on_debug = self.get_param_value(params, 'pause_on_debug')

        def debug_log(*items):
            log(
                'debug',
                items,
                pause_on_debug
            )

        def create_connection():
            for attempt_number in attempts(max_attempts):
                try:
                    irc = TwitchChatIRC()
                    irc.set_timeout(message_receive_timeout)
                    irc.join_channel(stream_id)
                    return irc
                except socket.gaierror as e:
                    self.retry(attempt_number, max_attempts, e, retry_timeout)

        twitch_chat_irc = create_connection()

        time_since_last_message = 0

        last_ping_time = time.time()

        # TODO make this param
        ping_every = 60  # how often to ping the server

        readbuffer = ''

        attempt_number = 0

        # test = 0
        timeout = Timeout(self.get_param_value(params, 'timeout'))
        while True:
            timeout.check_for_timeout()

            try:
                new_info = twitch_chat_irc.recv(buffer_size)

                if not new_info:
                    raise ConnectionError('Lost connection, reconnecting.')

                readbuffer += new_info

                if self._PING_TEXT in readbuffer:
                    twitch_chat_irc.send_raw(self._PONG_TEXT)

                matches = list(self._MESSAGE_REGEX.finditer(readbuffer))
                full_readbuffer = readbuffer.endswith('\r\n')
                if matches:
                    if not full_readbuffer:
                        # sometimes a buffer does not contain a full message
                        # last one is incomplete

                        span = matches[-1].span()

                        pass_on = readbuffer[span[0]:]

                        # check whether message was cut off
                        if '\r\n' in pass_on:  # last message not matched
                            # only pass on incomplete message

                            # readbuffer[span[1]:]
                            pass_on = pass_on[span[1]-span[0]:]

                        # actual message cut off (matched, but not complete)
                        else:
                            # remove the last match from being processed (as it is incomplete)
                            matches.pop()

                        # pass remaining information to next attempt
                        readbuffer = pass_on

                    else:
                        # the whole readbuffer was read correctly.
                        # reset the readbuffer
                        readbuffer = ''

                    time_since_last_message = 0

                    for match in matches:

                        data = self._parse_irc_item(match)

                        # test for missing keys
                        missing_keys = data.keys()-TwitchChatDownloader._KNOWN_IRC_KEYS

                        if missing_keys:
                            debug_log(
                                'Missing keys found: {}'.format(
                                    missing_keys),
                                'Original data: {}'.format(match.groups()),
                                'Parsed data: {}'.format(data)
                            )
                        # check whether to skip this message or not, based on its type

                        to_add = self.must_add_item(
                            data,
                            self._MESSAGE_GROUPS,
                            messages_groups_to_add,
                            messages_types_to_add
                        )

                        if not to_add:
                            continue

                        yield data

                elif full_readbuffer:
                    # No matches, but data has been read successfully.
                    # This means that we can safely reset the readbuffer.
                    # This is used to periodically reset the readbuffer,
                    # to avoid a massive buffer from forming.

                    log('debug','No matches found in "\n{}\n"'.format(
                            readbuffer.strip())) # never pause
                    readbuffer = ''

                current_time = time.time()

                time_since_last_ping = current_time - last_ping_time

                if time_since_last_ping > ping_every:
                    twitch_chat_irc.send_raw('PING')
                    last_ping_time = current_time

                # attempt_number = 0

            except socket.timeout:
                # print('time_since_last_message',time_since_last_message)
                if timeout is not None:
                    time_since_last_message += message_receive_timeout

                    if time_since_last_message >= timeout:
                        # TODO change to log
                        print('No data received in', timeout,
                              'seconds. Timing out.')
                        break

            except ConnectionError as e:
                twitch_chat_irc = create_connection()

    def get_chat_by_stream_id(self, stream_id, params):

        max_attempts = self.get_param_value(params, 'max_attempts')
        retry_timeout = self.get_param_value(params, 'retry_timeout')

        query = [{
            'operationName': 'StreamMetadata',
            'variables': {'channelLogin': stream_id.lower()}
        }]

        pause_on_debug = self.get_param_value(params, 'pause_on_debug')

        for attempt_number in attempts(max_attempts):
            try:
                stream_info = self._download_gql(query)[0]['data']['user']
                break
            except (UnexpectedHTML, RequestException) as e:
                self.retry(attempt_number, max_attempts, e, retry_timeout)

        is_live = multi_get(stream_info, 'stream', 'type') == 'live'
        title = multi_get(stream_info, 'lastBroadcast',
                          'title') if is_live else None


        return Chat(
            self,
            self._get_chat_messages_by_stream_id(
                stream_id, params),
            title=title,
            duration=None,
            is_live=is_live
        )

    def get_chat(self, params):

        url = self.get_param_value(params, 'url')

        for regex, function_name in self._REGEX_FUNCTION_MAP:
            match = re.search(regex, url)
            if match:
                return getattr(self, function_name)(match.group('id'), params)

        # if(match):
        #     match.group('id')
        #     return self.get_chat_by_video_id(match.group('id'), params)

            # if(match.group('id')):  # normal youtube video
            #     return

            # else:  # TODO add profile, etc.
            #     pass

    # def get_chat_messages(self, url):
    #     pass

    # # e.g. 'https://www.twitch.tv/spamfish/videos?filter=all'
    # _VALID_VIDEOS_URL = r'https?://(?:(?:www|go|m)\.)?twitch\.tv/(?P<id>[^/]+)/(?:videos|profile)'

    # # e.g. 'https://www.twitch.tv/vanillatv/clips?filter=clips&range=all'
    # _VALID_VIDEO_CLIPS_URL = r'https?://(?:(?:www|go|m)\.)?twitch\.tv/(?P<id>[^/]+)/(?:clips|videos/*?\?.*?\bfilter=clips)'

    # # e.g. 'https://www.twitch.tv/collections/wlDCoH0zEBZZbQ'
    # _VALID_COLLECTIONS_URL = r'https?://(?:(?:www|go|m)\.)?twitch\.tv/collections/(?P<id>[^/]+)'
