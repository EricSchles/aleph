import logging

from werkzeug.exceptions import BadRequest, NotFound
from flask import Blueprint, redirect, send_file, request
from apikit import jsonify, Pager, get_limit, get_offset, request_data

from aleph import authz
from aleph.core import get_archive, url_for, db
from aleph.model import Document, Entity, Reference, Collection
from aleph.logic import update_document
from aleph.events import log_event
from aleph.views.cache import enable_cache
from aleph.search.tabular import tabular_query, execute_tabular_query
from aleph.search.util import next_params
from aleph.views.util import get_document, get_tabular, get_page


log = logging.getLogger(__name__)
blueprint = Blueprint('documents_api', __name__)


@blueprint.route('/api/1/documents', methods=['GET'])
def index():
    collection_ids = request.args.getlist('collection')
    collection_ids = authz.collections_intersect(authz.READ, collection_ids)
    q = Document.all()
    clause = Collection.id.in_(collection_ids)
    q = q.filter(Document.collections.any(clause))
    hashes = request.args.getlist('content_hash')
    if len(hashes):
        q = q.filter(Document.content_hash.in_(hashes))
    return jsonify(Pager(q))


@blueprint.route('/api/1/documents/<int:document_id>')
def view(document_id):
    doc = get_document(document_id)
    enable_cache()
    data = doc.to_dict()
    log_event(request, document_id=doc.id)
    data['data_url'] = get_archive().generate_url(doc.meta)
    if data['data_url'] is None:
        data['data_url'] = url_for('documents_api.file',
                                   document_id=document_id)
    if doc.meta.is_pdf:
        data['pdf_url'] = data['data_url']
    else:
        try:
            data['pdf_url'] = get_archive().generate_url(doc.meta.pdf)
        except Exception as ex:
            log.info('Could not generate PDF url: %r', ex)
        if data.get('pdf_url') is None:
            data['pdf_url'] = url_for('documents_api.pdf',
                                      document_id=document_id)
    return jsonify(data)


@blueprint.route('/api/1/documents/<int:document_id>', methods=['POST', 'PUT'])
def update(document_id):
    document = get_document(document_id)
    # This is a special requirement for documents, so
    # they cannot escalate privs:
    authz.require(authz.collection_write(document.source_collection_id))
    data = request_data()
    document.update(data, writeable=authz.collections(authz.WRITE))
    db.session.commit()
    log_event(request, document_id=document.id)
    update_document(document)
    return view(document_id)


@blueprint.route('/api/1/documents/<int:document_id>/collections')
def view_collections(document_id):
    doc = get_document(document_id)
    return jsonify(doc.collection_ids)


@blueprint.route('/api/1/documents/<int:document_id>/collections',
                 methods=['POST', 'PUT'])
def update_collections(document_id):
    document = get_document(document_id)
    data = request_data()
    if not isinstance(data, list) or \
            False in [isinstance(d, int) for d in data]:
        raise BadRequest()
    document.update_collections(data, writeable=authz.collections(authz.WRITE))
    db.session.commit()
    log_event(request, document_id=document.id)
    update_document(document)
    return view_collections(document_id)


@blueprint.route('/api/1/documents/<int:document_id>/references')
def references(document_id):
    doc = get_document(document_id)
    q = db.session.query(Reference)
    q = q.filter(Reference.document_id == doc.id)
    q = q.filter(Reference.origin == 'regex')
    q = q.join(Entity)
    q = q.filter(Entity.state == Entity.STATE_ACTIVE)
    clause = Collection.id.in_(authz.collections(authz.READ))
    q = q.filter(Entity.collections.any(clause))
    q = q.order_by(Reference.weight.desc())
    return jsonify(Pager(q, document_id=document_id))


@blueprint.route('/api/1/documents/<int:document_id>/file')
def file(document_id):
    document = get_document(document_id)
    enable_cache(server_side=True)
    log_event(request, document_id=document.id)
    url = get_archive().generate_url(document.meta)
    if url is not None:
        return redirect(url)

    local_path = get_archive().load_file(document.meta)
    fh = open(local_path, 'rb')
    return send_file(fh, as_attachment=True,
                     attachment_filename=document.meta.file_name,
                     mimetype=document.meta.mime_type)


@blueprint.route('/api/1/documents/<int:document_id>/pdf')
def pdf(document_id):
    document = get_document(document_id)
    enable_cache(server_side=True)
    log_event(request, document_id=document.id)
    if document.type != Document.TYPE_TEXT:
        raise BadRequest("PDF is only available for text documents")
    pdf = document.meta.pdf
    url = get_archive().generate_url(pdf)
    if url is not None:
        return redirect(url)

    try:
        local_path = get_archive().load_file(pdf)
        fh = open(local_path, 'rb')
    except Exception as ex:
        raise NotFound("Missing PDF file: %r" % ex)
    return send_file(fh, mimetype=pdf.mime_type)


@blueprint.route('/api/1/documents/<int:document_id>/pages/<int:number>')
def page(document_id, number):
    document, page = get_page(document_id, number)
    enable_cache(server_side=True)
    return jsonify(page)


@blueprint.route('/api/1/documents/<int:document_id>/tables/<int:table_id>')
def table(document_id, table_id):
    document, tabular = get_tabular(document_id, table_id)
    enable_cache(vary_user=True)
    return jsonify(tabular)


@blueprint.route('/api/1/documents/<int:document_id>/tables/<int:table_id>/rows')
def rows(document_id, table_id):
    document, tabular = get_tabular(document_id, table_id)
    query = tabular_query(document_id, table_id, request.args)
    query['size'] = get_limit(default=100)
    query['from'] = get_offset()

    result = execute_tabular_query(query)
    params = next_params(request.args, result)
    if params is not None:
        result['next'] = url_for('documents_api.rows', document_id=document_id,
                                 table_id=table_id, **params)
    return jsonify(result)
