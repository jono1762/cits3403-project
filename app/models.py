from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

# Reports auto-expire this many days after creation. Authors can extend by
# clicking "Post it again" before expiry.
REPORT_LIFETIME_DAYS = 7


def _default_report_expiry():
    """Default `expires_at` for a freshly-created report."""
    return datetime.utcnow() + timedelta(days=REPORT_LIFETIME_DAYS)

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    # Optional uploaded avatar — UUID filename under static/uploads/.
    # NULL means "fall back to the initial-letter avatar".
    avatar_filename = db.Column(db.String(64), nullable=True)
    # Optional free-text bio shown on the public profile. Length capped at the
    # form layer (500 chars). Plain text — Jinja auto-escapes on render.
    bio = db.Column(db.Text, nullable=True)
    # Account creation time — drives anti-gaming on the Trending leaderboard:
    # only verifies / disputes from accounts older than the configured min
    # age count toward a report's trending score.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Whether the user's "Following" list is visible to other users.
    # The owner always sees their own list regardless of this flag.
    # server_default='1' so existing rows get backfilled when the column
    # is added — SQLite requires a SQL-level DEFAULT for NOT NULL adds.
    following_list_public = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    # Same idea for the Followers list — control whether others can see
    # who follows this user.
    followers_list_public = db.Column(db.Boolean, nullable=False, default=True, server_default='1')

    reports = db.relationship('Report', backref='author', lazy=True)
    verifications = db.relationship('Verification', backref='verifier', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ---- Aggregated reputation stats (computed live from related rows) ----
    # These run sums in Python over the `reports` relationship. Fine at the
    # current data scale; if the app grows, swap each one for a single SQL
    # aggregate against the verifications table.

    @property
    def verifications_received(self):
        """How many ✓ verify votes this user's reports have collected in total."""
        return sum(r.verify_count for r in self.reports)

    @property
    def disputes_received(self):
        """How many ✗ dispute votes this user's reports have collected in total."""
        return sum(r.dispute_count for r in self.reports)

    @property
    def trust_score(self):
        """Credibility percentage — share of incoming votes that are ✓ Verify.
        Returns None when the user has received no votes yet, so the UI can
        show "—" instead of a misleading 0%."""
        total = self.verifications_received + self.disputes_received
        if total == 0:
            return None
        return round(self.verifications_received / total * 100)

    # ---- Follow graph ----
    # Counts run a single SQL aggregate (count) — cheap even at scale.
    @property
    def follower_count(self):
        return Follow.query.filter_by(followed_id=self.id).count()

    @property
    def following_count(self):
        return Follow.query.filter_by(follower_id=self.id).count()

    def is_followed_by(self, user):
        """True if `user` already follows this user. False for guests / self / unknown."""
        if not getattr(user, 'is_authenticated', False):
            return False
        return Follow.query.filter_by(
            follower_id=user.id, followed_id=self.id
        ).first() is not None

    def is_mutual_with(self, other):
        """True if both users follow each other — the chat-system 'friend' check.
        Mutual followers' first messages auto-accept into the main Chats inbox;
        non-mutual messages start in the recipient's Requests tab."""
        if not other or other.id == self.id:
            return False
        a_to_b = Follow.query.filter_by(follower_id=self.id, followed_id=other.id).first()
        b_to_a = Follow.query.filter_by(follower_id=other.id, followed_id=self.id).first()
        return (a_to_b is not None) and (b_to_a is not None)

    @property
    def unread_message_count(self):
        """Total unread messages addressed to this user across every conversation —
        powers the small red badge on the sidebar 'Messages' link."""
        return ChatMessage.query.join(Conversation).filter(
            db.or_(Conversation.user_a_id == self.id,
                   Conversation.user_b_id == self.id),
            ChatMessage.sender_id != self.id,
            ChatMessage.read_at.is_(None),
        ).count()

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    marker_color = db.Column(db.String(7), nullable=False)

    reports = db.relationship('Report', backref='category', lazy=True)

class State(db.Model):
    __tablename__ = 'states'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(3), unique=True, nullable=False)   # e.g. NSW, VIC, WA
    name = db.Column(db.String(50), nullable=False)               # e.g. New South Wales

    cities = db.relationship('City', backref='state', lazy=True)

class City(db.Model):
    __tablename__ = 'cities'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    state_id = db.Column(db.Integer, db.ForeignKey('states.id'), nullable=False)

    reports = db.relationship('Report', backref='city', lazy=True)


class FavouriteLocation(db.Model):
    __tablename__ = 'favourite_locations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    city = db.relationship('City', foreign_keys=[city_id])

    __table_args__ = (
        db.UniqueConstraint('user_id', 'city_id', name='uq_user_city_fav'),
    )


class FavouriteReport(db.Model):
    __tablename__ = 'favourite_reports'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    report = db.relationship('Report', foreign_keys=[report_id])

    __table_args__ = (
        db.UniqueConstraint('user_id', 'report_id', name='uq_user_report_fav'),
    )

class Report(db.Model):
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True)
    # nullable so that deleting the author's account doesn't wipe their reports —
    # the author column is set to NULL and the byline renders as "deleted_user"
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    # optional free-text for extra detail like street name or landmark
    address = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Auto-expiry — after this datetime the report is hidden from public lists
    # and gets deleted by the next cleanup pass. Authors can reset it via the
    # "Post it again" button before it lapses.
    expires_at = db.Column(db.DateTime, default=_default_report_expiry, nullable=True)

    verifications = db.relationship('Verification', backref='report', lazy=True)
    # cascade so deleting a report also deletes its attached images/videos
    media = db.relationship('ReportMedia', backref='report', lazy=True, cascade='all, delete-orphan')
    # cascade so deleting a report also wipes its comment thread
    comments = db.relationship('Comment', backref='report', lazy=True, cascade='all, delete-orphan')

    @property
    def verify_count(self):
        return sum(1 for v in self.verifications if v.status == 'verify')

    @property
    def dispute_count(self):
        return sum(1 for v in self.verifications if v.status == 'dispute')

    @property
    def comment_count(self):
        return len(self.comments)

    @property
    def hours_until_expiry(self):
        """Whole hours until the report expires. Negative if already expired,
        None if no expiry set."""
        if not self.expires_at:
            return None
        delta = self.expires_at - datetime.utcnow()
        return int(delta.total_seconds() // 3600)

    @property
    def is_expiring_soon(self):
        """True when the report will expire in the next 24 hours (and isn't
        already expired). Used to drive the orange banner + button styling."""
        h = self.hours_until_expiry
        return h is not None and 0 <= h < 24

    @property
    def expiry_label(self):
        """Short human label for the countdown badge — '7 days left',
        '1 day left', '<1 day left'. Returns None if no expiry set."""
        h = self.hours_until_expiry
        if h is None:
            return None
        if h < 0:
            return 'expired'
        if h < 24:
            return '<1 day left'
        days = h // 24
        return f'{days} day{"s" if days != 1 else ""} left'

    def vote_by(self, user):
        """Return the given user's vote on this report — 'verify', 'dispute', or None."""
        if not getattr(user, 'is_authenticated', False):
            return None
        for v in self.verifications:
            if v.user_id == user.id:
                return v.status
        return None

class ReportMedia(db.Model):
    __tablename__ = 'report_media'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    filename = db.Column(db.String(64), nullable=False)        # stored UUID-based name on disk
    original_name = db.Column(db.String(255), nullable=False)  # what the user called it
    media_type = db.Column(db.String(10), nullable=False)      # 'image' or 'video'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class Verification(db.Model):
    __tablename__ = 'verifications'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # 'verify' = user confirms the report is accurate; 'dispute' = user denies it.
    # Each (user, report) pair has at most one row — flipping vote updates this.
    status = db.Column(db.String(10), nullable=False, default='verify')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    # nullable so deleting the author keeps the comment but anonymises it
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # plain text only — Jinja auto-escapes on render so HTML/script tags become
    # inert. body is capped at the route layer (2000 chars) to keep abuse manageable.
    # body can be empty if the comment carries media instead — server enforces
    # that at least one of (body, media) is present.
    body = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User')
    # cascade so deleting a comment also wipes its attached images/videos
    media = db.relationship('CommentMedia', backref='comment', lazy=True, cascade='all, delete-orphan')
    # votes on the comment itself (separate from votes on the parent report)
    votes = db.relationship('CommentVote', backref='comment', lazy=True)

    @property
    def verify_count(self):
        return sum(1 for v in self.votes if v.status == 'verify')

    @property
    def dispute_count(self):
        return sum(1 for v in self.votes if v.status == 'dispute')

    def vote_by(self, user):
        """Return the given user's vote on this comment — 'verify', 'dispute', or None."""
        if not getattr(user, 'is_authenticated', False):
            return None
        for v in self.votes:
            if v.user_id == user.id:
                return v.status
        return None


class CommentMedia(db.Model):
    __tablename__ = 'comment_media'
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=False)
    filename = db.Column(db.String(64), nullable=False)        # uuid stored name on disk
    original_name = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(10), nullable=False)      # 'image' or 'video'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class CommentVote(db.Model):
    __tablename__ = 'comment_votes'
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # 'verify' = user agrees with the comment; 'dispute' = user disagrees.
    # Same toggle semantics as Verification on Report.
    status = db.Column(db.String(10), nullable=False, default='verify')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Follow(db.Model):
    """Directed follow edge — follower_id is following followed_id.
    The unique constraint stops a user from following the same person twice."""
    __tablename__ = 'follows'
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('follower_id', 'followed_id', name='uq_follow_pair'),
    )


class Conversation(db.Model):
    """One row per (canonical) pair of users who have ever exchanged a message.
    user_a_id is always the smaller id so we never store the same pair twice
    in either direction. accepted=False means it's a 'message request' —
    visible in the recipient's Requests tab, not the main Chats."""
    __tablename__ = 'conversations'
    id = db.Column(db.Integer, primary_key=True)
    user_a_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user_b_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    initiator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # auto-True when the two users are mutual followers (FB-style "friends");
    # otherwise flips to True the moment the recipient replies or accepts
    accepted = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_a = db.relationship('User', foreign_keys=[user_a_id])
    user_b = db.relationship('User', foreign_keys=[user_b_id])
    messages = db.relationship('ChatMessage', backref='conversation', lazy=True,
                               cascade='all, delete-orphan',
                               order_by='ChatMessage.created_at')

    __table_args__ = (
        db.UniqueConstraint('user_a_id', 'user_b_id', name='uq_conv_pair'),
    )

    def other(self, user):
        """Return the User on the other side of the conversation from `user`."""
        return self.user_b if user.id == self.user_a_id else self.user_a

    def is_request_for(self, user):
        """True if this conversation should sit in `user`'s Requests tab —
        i.e. it's pending and they didn't initiate it."""
        return (not self.accepted) and self.initiator_id != user.id


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # plain text — Jinja auto-escape + JS textContent guards XSS the same way
    # we do for comments. Server caps length at the route layer. Body can be
    # empty if the message carries media instead.
    body = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    sender = db.relationship('User', foreign_keys=[sender_id])
    # cascade so deleting a message also wipes any attached images / videos
    media = db.relationship('ChatMessageMedia', backref='message', lazy=True,
                            cascade='all, delete-orphan')


class ChatMessageMedia(db.Model):
    __tablename__ = 'chat_message_media'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_messages.id'), nullable=False)
    filename = db.Column(db.String(64), nullable=False)        # uuid stored name on disk
    original_name = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(10), nullable=False)      # 'image' or 'video'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class BlockedUser(db.Model):
    """Chat-only block. blocker_id has stopped accepting messages from blocked_id.
    Blocked users can still see the blocker's posts / profile / comments —
    only the messaging surface is restricted."""
    __tablename__ = 'blocked_users'
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('blocker_id', 'blocked_id', name='uq_block_pair'),
    )