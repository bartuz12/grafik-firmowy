from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, subqueryload
from datetime import datetime, date, time

# Importy z głównych plików aplikacji
# --- POPRAWKA: Usunięto 'rq' z importu, aby wyłączyć Redisa ---
from extensions import db
from models import Trip, Signup, User, Recipient

# Usunięto import 'from forms import TripForm, SignupForm'
from utils import admin_or_manager_required, send_email_in_background

trips_bp = Blueprint('trips', __name__)


def auto_signup_golden_workers(trip):
    """
    Logika dla "złotego pracownika": automatycznie zapisuje go na każde nowe zlecenie
    ze statusem 'wstępnie zapisany'.
    """
    golden_workers = User.query.filter_by(status='złoty pracownik').all()
    if not golden_workers:
        return

    golden_worker_ids = {worker.id for worker in golden_workers}

    existing_signups = db.session.query(Signup.user_id).filter(
        Signup.trip_id == trip.id,
        Signup.user_id.in_(golden_worker_ids)
    ).all()
    existing_user_ids = {signup.user_id for signup in existing_signups}

    new_signups = []
    for worker_id in (golden_worker_ids - existing_user_ids):
        new_signups.append(Signup(trip_id=trip.id, user_id=worker_id, status='wstępnie zapisany'))

    if new_signups:
        db.session.add_all(new_signups)

# --- Trasy Główne Związane ze Zleceniami ---

@trips_bp.route('/add', methods=['GET', 'POST'])
@login_required
@admin_or_manager_required
def add_trip():
    """
    Logika dodawania nowego zlecenia przez administratora/kierownika.
    """
    if request.method == 'POST':
        try:
            spots_val_str = request.form.get('spots')
            spots_val = int(spots_val_str) if spots_val_str else 1
            
            if not 1 <= spots_val <= 7:
                flash('Liczba miejsc musi być w zakresie od 1 do 7.', 'error')
                return render_template('add_trip.html', form_data=request.form)
        except (ValueError, TypeError):
            flash('Liczba miejsc musi być liczbą całkowitą.', 'error')
            return render_template('add_trip.html', form_data=request.form)

        new_trip = Trip(
            title=request.form.get('title'),
            trip_date=datetime.strptime(request.form.get('trip_date'), '%Y-%m-%d').date(),
            spots=spots_val,
            is_confirmed='is_confirmed' in request.form,
            notes=request.form.get('notes')
        )
        db.session.add(new_trip)
        db.session.commit()

        db.session.add(Signup(trip_id=new_trip.id, user_id=current_user.id, status='potwierdzony'))
        
        auto_signup_golden_workers(new_trip)
        
        db.session.commit()

        # --- POPRAWKA: Tymczasowo wyłączono powiadomienia RQ ---
        # Powiadomienie e-mail (asynchronicznie)
        # users_to_notify = User.query.filter(User.status.in_(['pracownik', 'złoty pracownik'])).all()
        # for user in users_to_notify:
        #     # Używamy rq.enqueue importowanego z extensions
        #     rq.enqueue(
        #         send_email_in_background,
        #         user.email,
        #         f'Nowe zlecenie w grafiku: {new_trip.title}',
        #         'email/new_trip',
        #         trip=new_trip,
        #         user=user
        #     )
        pass # Pomijamy wysyłkę e-maila

        flash('Nowe zlecenie zostało dodane.', 'success')
        return redirect(url_for('trips.trip_details', trip_id=new_trip.id))

    return render_template('add_trip.html', form_data={})


@trips_bp.route('/<int:trip_id>')
@login_required
def trip_details(trip_id):
    """
    Wyświetla stronę ze szczegółami zlecenia.
    """
    trip = Trip.query.options(
        subqueryload(Trip.signups).joinedload(Signup.user)
    ).get_or_404(trip_id)

    if trip.is_archived and current_user.status not in ['admin', 'kierownik']:
        flash('To zlecenie zostało zarchiwizowane i nie jest już dostępne.', 'error')
        return redirect(url_for('main.dashboard'))

    signups = trip.signups
    user_signup = next((s for s in signups if s.user_id == current_user.id), None)
    
    occupied_spots = sum(
        1 for s in signups if s.status in ['potwierdzony', 'wstępnie zapisany']
    )
    
    return render_template(
        'trip_details.html',
        trip=trip,
        signups=signups,
        user_signup=user_signup,
        is_past_trip=(trip.trip_date < date.today()),
        available_spots=(trip.spots or 0) - occupied_spots
    )


@trips_bp.route('/<int:trip_id>/edit', methods=['POST'])
@login_required
@admin_or_manager_required
def edit_trip(trip_id):
    """
    Uniwersalna funkcja do edycji zlecenia.
    """
    trip = Trip.query.get_or_404(trip_id)
    try:
        if 'spots' in request.form:
            spots_str = request.form.get('spots')
            trip.spots = int(spots_str) if spots_str else 1
        if 'start_time' in request.form:
            start_time_str = request.form.get('start_time')
            trip.start_time = time.fromisoformat(start_time_str) if start_time_str else None
        if 'departure_time' in request.form:
            departure_time_str = request.form.get('departure_time')
            trip.departure_time = time.fromisoformat(departure_time_str) if departure_time_str else None
        if 'work_start_time' in request.form:
            work_start_time_str = request.form.get('work_start_time')
            trip.work_start_time = time.fromisoformat(work_start_time_str) if work_start_time_str else None
        if 'work_end_time' in request.form:
            work_end_time_str = request.form.get('work_end_time')
            trip.work_end_time = time.fromisoformat(work_end_time_str) if work_end_time_str else None
        if 'kilometers' in request.form:
            kilometers_str = request.form.get('kilometers', '').replace(',', '.')
            trip.kilometers = float(kilometers_str) if kilometers_str else None
        if 'notes' in request.form:
            trip.notes = request.form.get('notes')

        trip.is_confirmed = 'is_confirmed' in request.form
        trip.manager_was_passenger = 'manager_was_passenger' in request.form
        
        trip.last_modified = datetime.utcnow()
        db.session.commit()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'success', 'message': 'Zmiany zostały zapisane.'}), 200
        else:
            flash('Zmiany zostały zapisane.', 'success')
            return redirect(url_for('trips.trip_details', trip_id=trip.id))

    except (ValueError, TypeError) as e:
        db.session.rollback()
        error_message = f'Błąd formatu danych: {e}'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': error_message}), 400
        else:
            flash(error_message, 'error')
            return redirect(url_for('trips.trip_details', trip_id=trip.id))
    except Exception as e:
        db.session.rollback()
        error_message = f'Wystąpił nieoczekiwany błąd serwera: {e}'
        current_app.logger.error(f"Błąd w edit_trip (ID: {trip_id}): {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': error_message}), 500
        else:
            flash(error_message, 'error')
            return redirect(url_for('trips.trip_details', trip_id=trip.id))


@trips_bp.route('/<int:trip_id>/signup', methods=['POST'])
@login_required
def signup_trip(trip_id):
    """
    Logika zapisów dla pracowników.
    """
    trip = Trip.query.get_or_404(trip_id)
    action = request.form.get('action')
    user_signup = Signup.query.filter_by(trip_id=trip.id, user_id=current_user.id).first()

    if user_signup:
        if action == 'confirm' and user_signup.status == 'wstępnie zapisany':
            user_signup.status = 'potwierdzony'
            flash('Twój udział w zleceniu został potwierdzony.', 'success')
        elif action == 'cancel':
            db.session.delete(user_signup)
            flash('Zrezygnowałeś/aś z udziału w zleceniu (lub niedyspozycji).', 'success')
    
    else:
        if action == 'signup':
            occupied_spots = Signup.query.filter(
                Signup.trip_id == trip.id,
                Signup.status.in_(['potwierdzony', 'wstępnie zapisany'])
            ).count()
            
            if (trip.spots or 0) - occupied_spots > 0:
                new_status = 'potwierdzony'
                flash('Zostałeś zapisany/a na zlecenie.', 'success')
            else:
                new_status = 'rezerwowy'
                flash('Brak wolnych miejsc. Zostałeś zapisany/a na listę rezerwową.', 'info')
            db.session.add(Signup(trip_id=trip.id, user_id=current_user.id, status=new_status))
        
        elif action == 'decline':
            db.session.add(Signup(trip_id=trip.id, user_id=current_user.id, status='niedyspozycyjny'))
            flash('Zgłoszono niedyspozycję dla tego zlecenia.', 'info')

    db.session.commit()
    return redirect(url_for('trips.trip_details', trip_id=trip.id))


@trips_bp.route('/<int:trip_id>/delete', methods=['POST'])
@login_required
@admin_or_manager_required
def delete_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    db.session.delete(trip)
    db.session.commit()
    flash('Zlecenie zostało trwale usunięte.', 'success')
    return redirect(url_for('main.dashboard'))

@trips_bp.route('/<int:trip_id>/send-to-office', methods=['POST'])
@login_required
@admin_or_manager_required
def send_to_office(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    
    signups = Signup.query.options(
        joinedload(Signup.user)
    ).filter(
        Signup.trip_id == trip.id,
        Signup.status.in_(['potwierdzony', 'wstępnie zapisany'])
    ).all()
    
    recipients = Recipient.query.filter_by(user_id=current_user.id).all()
    recipient_emails = [r.email for r in recipients]

    if not recipient_emails:
        flash('Nie zdefiniowano żadnych odbiorców w Twoim profilu.', 'error')
    else:
        subject = f"Lista Uczestników: {trip.title} - {trip.trip_date.strftime('%d.%m.%Y')}"
        
        # --- POPRAWKA: Tymczasowo wyłączono powiadomienia RQ ---
        # Używamy rq.enqueue importowanego z extensions
        # rq.enqueue(
        #     send_email_in_background,
        #     recipient_emails,
        #     subject,
        #     'email/trip_participants',
        #     trip=trip,
        #     signups=signups
        # )
        # flash('Lista uczestników została wysłana do biura.', 'success')
        pass # Pomijamy wysyłkę e-maila
        flash('Wysyłanie e-maili jest tymczasowo wyłączone (RQ).', 'info')

    return redirect(url_for('trips.trip_details', trip_id=trip.id))


