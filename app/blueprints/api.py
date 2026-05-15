"""JSON API endpoints — favourites, conversations / chat, and comments.
 
These are the fetch-target URLs the frontend JS calls; HTML page renders
live in app/routes.py and the user/auth/reports blueprints."""
import os
import uuid
from flask import Blueprint, url_for, request, jsonify, current_app as app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
 
from ..models import (
    db, User, City, Report, Comment, CommentMedia, CommentVote,
    Conversation, ChatMessage, ChatMessageMedia,
    FavouriteLocation, FavouriteReport, BlockedUser,
    utcnow,
)
from .reports import _validate_uploads, MAX_MEDIA_FILES, COMMENT_MAX_LENGTH
from .users import _is_blocked
 
bp = Blueprint('api', __name__)
 
 
@bp.route('/api/favourites/locations', methods=['GET'])
@login_required
def api_get_favourite_locations():
    fav_rows = FavouriteLocation.query.filter_by(user_id=current_user.id).all()
    data = []
    for f in fav_rows:
        city = f.city
        if not city:
            continue
        data.append({
            'city_id': city.id,
            'name': city.name,
            'state_code': city.state.code if getattr(city, 'state', None) else '',
        })
    return jsonify(data)
 
 
@bp.route('/api/favourites/location/<int:city_id>', methods=['POST'])
@login_required
def api_add_favourite_location(city_id):
    city = db.get_or_404(City, city_id)
    existing = FavouriteLocation.query.filter_by(user_id=current_user.id, city_id=city.id).first()
    if not existing:
        fav = FavouriteLocation(user_id=current_user.id, city_id=city.id)
        db.session.add(fav)
        db.session.commit()
    return jsonify({'added': True})
 
 
@bp.route('/api/favourites/location/<int:city_id>', methods=['DELETE'])
@login_required
def api_remove_favourite_location(city_id):
    fav = FavouriteLocation.query.filter_by(user_id=current_user.id, city_id=city_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
    return jsonify({'removed': True})
 
 
@bp.route('/api/favourites/reports', methods=['GET'])
@login_required
def api_get_favourite_reports():
    fav_rows = FavouriteReport.query.filter_by(user_id=current_user.id).all()
    return jsonify([
        {'report_id': row.report_id}
        for row in fav_rows
    ])
 
 
@bp.route('/api/favourites/report/<int:report_id>', methods=['POST'])
@login_required
def api_add_favourite_report(report_id):
    report = db.get_or_404(Report, report_id)
    existing = FavouriteReport.query.filter_by(user_id=current_user.id, report_id=report.id).first()
    if not existing:
        db.session.add(FavouriteReport(user_id=current_user.id, report_id=report.id))
        db.session.commit()
    return jsonify({'added': True})
 
 
@bp.route('/api/favourites/report/<int:report_id>', methods=['DELETE'])
@login_required
def api_remove_favourite_report(report_id):
    fav = FavouriteReport.query.filter_by(user_id=current_user.id, report_id=report_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
    return jsonify({'removed': True})
 
 
# 1-on-1 messaging. Conversation rows store the per-pair state (accepted vs
# request); ChatMessage rows store the actual messages.
# Body is plain text — same XSS-safe pattern as comments (Jinja auto-escape +
# textContent on the JS side).
 
CHAT_MESSAGE_MAX_LENGTH = 2000
 
 
def _find_or_create_conversation(sender, recipient):
    """Look up the canonical (smaller-id-first) Conversation row between
    sender + recipient, creating it on demand. New conversations auto-accept
    when the two users are mutual followers; otherwise they start as a
    pending message-request."""
    me, them = sorted([sender.id, recipient.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first()
    if conv is None:
        conv = Conversation(
            user_a_id=me,
            user_b_id=them,
            initiator_id=sender.id,
            accepted=sender.is_mutual_with(recipient),
        )
        db.session.add(conv)
        db.session.flush()
    elif (not conv.accepted) and conv.initiator_id != sender.id:
        # the recipient is replying → that auto-accepts the pending request
        conv.accepted = True
    return conv
 
 
def _serialize_conversation_summary(conv, viewer):
    """Compact JSON shape for the inbox list — last message preview + counts."""
    other = conv.other(viewer)
    last = ChatMessage.query.filter_by(conversation_id=conv.id) \
        .order_by(ChatMessage.created_at.desc()).first()
    unread = ChatMessage.query.filter(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.sender_id != viewer.id,
        ChatMessage.read_at.is_(None),
    ).count()
    return {
        'user_id': other.id,
        'username': other.username,
        'avatar_initial': other.username[:1].upper(),
        'avatar_url': (url_for('static', filename=f'uploads/{other.avatar_filename}')
                       if other.avatar_filename else None),
        'profile_url': url_for('users.user_profile_page', username=other.username),
        'last_body': last.body if last else '',
        'last_at': conv.last_message_at.isoformat() if conv.last_message_at else None,
        'last_sender_is_me': bool(last and last.sender_id == viewer.id),
        'unread': unread,
        'is_request': conv.is_request_for(viewer),
        'accepted': conv.accepted,
    }
 
 
@bp.route('/api/users/<int:user_id>')
@login_required
def api_user_brief(user_id):
    """Minimal user-info endpoint used by the chat page when the inbox doesn't
    yet contain this user (fresh conversation started from a profile page)."""
    if user_id == current_user.id:
        return jsonify({'error': "That's you."}), 400
    u = db.get_or_404(User, user_id)
    return jsonify({
        'user_id': u.id,
        'username': u.username,
        'avatar_initial': u.username[:1].upper(),
        'avatar_url': (url_for('static', filename=f'uploads/{u.avatar_filename}')
                       if u.avatar_filename else None),
        'profile_url': url_for('users.user_profile_page', username=u.username),
        'is_blocked': _is_blocked(current_user.id, u.id),
    })
 
 
@bp.route('/api/conversations')
@login_required
def api_list_conversations():
    """Return chats and requests as two separate lists, both newest-first.
    Conversations with users I've blocked are filtered out of both lists —
    they reappear in the inbox if I unblock the user later."""
    blocked_ids = {
        row.blocked_id
        for row in BlockedUser.query.filter_by(blocker_id=current_user.id).all()
    }
    convs = Conversation.query.filter(
        db.or_(Conversation.user_a_id == current_user.id,
               Conversation.user_b_id == current_user.id)
    ).order_by(Conversation.last_message_at.desc()).all()
 
    chats = []
    requests_list = []
    for conv in convs:
        other = conv.other(current_user)
        if other.id in blocked_ids:
            continue  # hide conversations with blocked users
        item = _serialize_conversation_summary(conv, current_user)
        if conv.is_request_for(current_user):
            requests_list.append(item)
        else:
            chats.append(item)
    return jsonify({
        'chats': chats,
        'requests': requests_list,
        'unread_total': current_user.unread_message_count,
    })
 
 
@bp.route('/api/conversations/<int:user_id>/messages', methods=['GET'])
@login_required
def api_get_messages(user_id):
    """Fetch the message history with a specific user. Optional ?since=<iso> to
    only get messages newer than the given timestamp (used by the polling loop)."""
    other = db.get_or_404(User, user_id)
    me, them = sorted([current_user.id, other.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first()
    if conv is None:
        return jsonify({
            'messages': [], 'accepted': False, 'is_request': False,
            'is_blocked': _is_blocked(current_user.id, other.id),
            'blocked_by_them': _is_blocked(other.id, current_user.id),
        })
 
    since = request.args.get('since')
    q = ChatMessage.query.filter_by(conversation_id=conv.id)
    if since:
        try:
            cutoff = datetime.fromisoformat(since)
            q = q.filter(ChatMessage.created_at > cutoff)
        except ValueError:
            pass
    msgs = q.order_by(ChatMessage.created_at.asc()).all()
 
    return jsonify({
        'accepted': conv.accepted,
        'is_request': conv.is_request_for(current_user),
        'is_blocked': _is_blocked(current_user.id, other.id),
        'messages': [{
            'blocked_by_them': _is_blocked(other.id, current_user.id),
            'id': m.id,
            'body': m.body,
            'sender_id': m.sender_id,
            'sender_is_me': m.sender_id == current_user.id,
            'created_at': m.created_at.isoformat(),
            'media': [
                {
                    'type': mm.media_type,
                    'url': url_for('static', filename=f'uploads/{mm.filename}'),
                    'original_name': mm.original_name,
                }
                for mm in m.media
            ],
        } for m in msgs],
    })
 
 
@bp.route('/api/conversations/<int:user_id>/messages', methods=['POST'])
@login_required
def api_send_message(user_id):
    """Send a message. Accepts JSON ({body}) for text-only OR multipart/form-data
    (body + media[]) when files are attached. First message creates the
    conversation; recipient replying auto-accepts a pending request."""
    if user_id == current_user.id:
        return jsonify({'error': "You can't message yourself."}), 400
    recipient = db.get_or_404(User, user_id)
 
    # Block check — recipient may have blocked the current user from messaging.
    # Show a generic "can't reach this user" message rather than confirming
    # the block (avoids leaking the recipient's privacy choice).
    if _is_blocked(blocker_id=recipient.id, blocked_id=current_user.id):
        return jsonify({'error': "This user isn't accepting messages from you."}), 403
 
    if request.content_type and 'multipart/form-data' in request.content_type:
        body = (request.form.get('body') or '').strip()
        files = [f for f in request.files.getlist('media') if f and f.filename]
    else:
        payload = request.get_json(silent=True) or {}
        body = (payload.get('body') or '').strip()
        files = []
 
    if not body and not files:
        return jsonify({'error': 'Message cannot be empty.'}), 400
    if len(body) > CHAT_MESSAGE_MAX_LENGTH:
        return jsonify({'error': f'Message too long (max {CHAT_MESSAGE_MAX_LENGTH} characters).'}), 400
    if len(files) > MAX_MEDIA_FILES:
        return jsonify({'error': f'Too many files (max {MAX_MEDIA_FILES}).'}), 400
    sniffs, err = _validate_uploads(files)
    if err:
        return jsonify({'error': err}), 400
 
    conv = _find_or_create_conversation(current_user, recipient)
    msg = ChatMessage(conversation_id=conv.id, sender_id=current_user.id, body=body)
    db.session.add(msg)
    db.session.flush()  # need msg.id for ChatMessageMedia FK
 
    # save uploaded files to disk + DB; clean up disk on error
    saved_paths = []
    try:
        for f, (media_type, ext) in zip(files, sniffs):
            stored_name = f'{uuid.uuid4().hex}.{ext}'
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
            f.save(save_path)
            saved_paths.append(save_path)
            db.session.add(ChatMessageMedia(
                message_id=msg.id,
                filename=stored_name,
                original_name=secure_filename(f.filename) or stored_name,
                media_type=media_type,
            ))
        conv.last_message_at = utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()
        for p in saved_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        raise
 
    return jsonify({
        'id': msg.id,
        'body': msg.body,
        'sender_id': msg.sender_id,
        'sender_is_me': True,
        'created_at': msg.created_at.isoformat(),
        'accepted': conv.accepted,
        'media': [
            {
                'type': m.media_type,
                'url': url_for('static', filename=f'uploads/{m.filename}'),
                'original_name': m.original_name,
            }
            for m in msg.media
        ],
    }), 201
 
 
@bp.route('/api/conversations/<int:user_id>/accept', methods=['POST'])
@login_required
def api_accept_conversation(user_id):
    """Move a pending message-request into the main Chats inbox."""
    other = db.get_or_404(User, user_id)
    me, them = sorted([current_user.id, other.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first_or_404()
    # only the recipient can accept (the initiator already had it in their Chats)
    if conv.initiator_id == current_user.id:
        return jsonify({'error': "You started this conversation, nothing to accept."}), 400
    conv.accepted = True
    db.session.commit()
    return jsonify({'accepted': True})
 
 
@bp.route('/api/conversations/<int:user_id>/read', methods=['POST'])
@login_required
def api_mark_read(user_id):
    """Mark every unread message addressed to me in this conversation as read.
    Called when the recipient opens the thread."""
    other = db.get_or_404(User, user_id)
    me, them = sorted([current_user.id, other.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first()
    if conv is None:
        return jsonify({'ok': True, 'marked': 0})
    now = utcnow()
    rows = ChatMessage.query.filter(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.sender_id != current_user.id,
        ChatMessage.read_at.is_(None),
    ).all()
    for m in rows:
        m.read_at = now
    db.session.commit()
    return jsonify({'ok': True, 'marked': len(rows)})
 
 
@bp.route('/api/messages/<int:message_id>', methods=['DELETE'])
@login_required
def api_delete_message(message_id):
    """Sender-only — wipes the chat message and its media (DB rows + files)."""
    msg = db.get_or_404(ChatMessage, message_id)
    if msg.sender_id != current_user.id:
        return jsonify({'error': "You can't delete someone else's message."}), 403
 
    for m in msg.media:
        disk_path = os.path.join(app.config['UPLOAD_FOLDER'], m.filename)
        try:
            os.remove(disk_path)
        except OSError:
            pass
 
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'ok': True})
 
 
# Comments — body stored as plain text and rendered with Jinja's default auto-
# escape, so HTML/JS in user input becomes inert text (XSS-safe). The frontend
# uses textContent (not innerHTML) when injecting new comments without reload.
 
def _serialize_comment(comment, current_user_id=None):
    """Shared comment-to-JSON shape for the create endpoint and any future list endpoint."""
    author = comment.author
    return {
        'id': comment.id,
        'body': comment.body,
        'author_username': author.username if author else 'deleted_user',
        'author_url': url_for('users.user_profile_page', username=author.username) if author else None,
        'author_initial': (author.username[:1].upper() if author else '?'),
        'author_avatar_url': (url_for('static', filename=f'uploads/{author.avatar_filename}')
                              if author and author.avatar_filename else None),
        'created_at': comment.created_at.strftime('%d %b %Y, %H:%M'),
        'is_own': comment.user_id == current_user_id,
        'verify_count': comment.verify_count,
        'dispute_count': comment.dispute_count,
        'user_vote': None,  # fresh comments — author can't vote on their own
        'media': [
            {
                'type': m.media_type,
                'url': url_for('static', filename=f'uploads/{m.filename}'),
                'original_name': m.original_name,
            }
            for m in comment.media
        ],
    }
 
 
@bp.route('/api/reports/<int:report_id>/comments', methods=['POST'])
@login_required
def api_create_comment(report_id):
    """Accepts either JSON ({body}) for text-only or multipart/form-data
    (body + media[]) when the user attached images / videos."""
    report = db.get_or_404(Report, report_id)
 
    if request.content_type and 'multipart/form-data' in request.content_type:
        body = (request.form.get('body') or '').strip()
        files = [f for f in request.files.getlist('media') if f and f.filename]
    else:
        payload = request.get_json(silent=True) or {}
        body = (payload.get('body') or '').strip()
        files = []
 
    # at least one of (text, media) must be present
    if not body and not files:
        return jsonify({'error': 'Comment cannot be empty.'}), 400
    if len(body) > COMMENT_MAX_LENGTH:
        return jsonify({'error': f'Comment too long (max {COMMENT_MAX_LENGTH} characters).'}), 400
    if len(files) > MAX_MEDIA_FILES:
        return jsonify({'error': f'Too many files (max {MAX_MEDIA_FILES}).'}), 400
    sniffs, err = _validate_uploads(files)
    if err:
        return jsonify({'error': err}), 400
 
    comment = Comment(report_id=report.id, user_id=current_user.id, body=body)
    db.session.add(comment)
    db.session.flush()  # populate comment.id so CommentMedia rows can FK to it
 
    # save each file to disk + DB; if anything fails halfway, clean up the disk files
    saved_paths = []
    try:
        for f, (media_type, ext) in zip(files, sniffs):
            stored_name = f'{uuid.uuid4().hex}.{ext}'
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
            f.save(save_path)
            saved_paths.append(save_path)
            db.session.add(CommentMedia(
                comment_id=comment.id,
                filename=stored_name,
                original_name=secure_filename(f.filename) or stored_name,
                media_type=media_type,
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        for p in saved_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        raise
 
    return jsonify(_serialize_comment(comment, current_user_id=current_user.id)), 201
 
 
@bp.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def api_delete_comment(comment_id):
    """Comment author only — wipes the comment, its media (DB + disk), and any votes."""
    comment = db.get_or_404(Comment, comment_id)
    if comment.user_id != current_user.id:
        return jsonify({'error': "You can't delete someone else's comment."}), 403
 
    # remove disk files first; the DB rows go via cascade on the relationship
    for m in comment.media:
        disk_path = os.path.join(app.config['UPLOAD_FOLDER'], m.filename)
        try:
            os.remove(disk_path)
        except OSError:
            pass
 
    # CommentVote has no cascade on the model, clear them by hand
    CommentVote.query.filter_by(comment_id=comment.id).delete()
 
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'ok': True})
 
 
@bp.route('/api/comments/<int:comment_id>/vote', methods=['POST'])
@login_required
def api_vote_comment(comment_id):
    """Verify / dispute a comment — same toggle semantics as report-vote.
    Comment author can't vote on their own comment."""
    comment = db.get_or_404(Comment, comment_id)
    if comment.user_id == current_user.id:
        return jsonify({'error': "You can't vote on your own comment."}), 400
 
    payload = request.get_json(silent=True) or {}
    new_status = payload.get('status') or request.form.get('status')
    if new_status not in ('verify', 'dispute'):
        return jsonify({'error': 'Invalid status.'}), 400
 
    existing = CommentVote.query.filter_by(comment_id=comment.id, user_id=current_user.id).first()
    if existing:
        if existing.status == new_status:
            db.session.delete(existing)  # click same button → un-vote
            user_vote = None
        else:
            existing.status = new_status  # flip vote
            user_vote = new_status
    else:
        db.session.add(CommentVote(comment_id=comment.id, user_id=current_user.id, status=new_status))
        user_vote = new_status
    db.session.commit()
 
    return jsonify({
        'verify_count': CommentVote.query.filter_by(comment_id=comment.id, status='verify').count(),
        'dispute_count': CommentVote.query.filter_by(comment_id=comment.id, status='dispute').count(),
        'user_vote': user_vote,
    })
 
 
 