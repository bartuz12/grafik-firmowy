#
# TEN KOD NALEŻY DODAĆ DO TWOJEGO PLIKU `routes/trips.py`
#
# Upewnij się, że na górze pliku `routes/trips.py` masz te importy:
#
# from flask import Blueprint, render_template, request, flash, redirect, url_for
# from flask_login import login_required, current_user
# from models import db, Trip, Signup, User
#
# Zakładamy, że twój Blueprint nazywa się `trips_bp`
#
# ... (tutaj Twój istniejący, działający kod dla /trip/add i GET /trip/<id>) ...


# ==========================================================
# === NOWA LOGIKA - NAPRAWIA 4 BŁĘDY FAILED ===
# ==========================================================

@trips_bp.route('/trip/<int:trip_id>/signup', methods=['POST'])
@login_required
def signup_for_trip(trip_id):
    trip = db.session.get(Trip, trip_id)
    if not trip:
        flash('Zlecenie nie istnieje.', 'error')
        return redirect(url_for('main.dashboard')) # Przekieruj do dashboardu
    
    # Sprawdź, czy użytkownik już jest zapisany (naprawia FAILED test_user_cannot_signup_twice)
    existing_signup = Signup.query.filter_by(trip_id=trip.id, user_id=current_user.id).first()
    if existing_signup:
        flash('Jesteś już zapisany na to zlecenie.', 'info')
        return redirect(url_for('trips.trip_details', trip_id=trip_id))

    # Sprawdź liczbę miejsc (naprawia FAILED test_user_cannot_signup_for_full_trip)
    # Używamy statusu 'potwierdzony' do liczenia zajętych miejsc
    confirmed_signups_count = Signup.query.filter_by(trip_id=trip.id, status='potwierdzony').count()
    
    if confirmed_signups_count >= trip.spots:
        flash('Brak wolnych miejsc na to zlecenie.', 'error')
        return redirect(url_for('trips.trip_details', trip_id=trip_id))

    # Dodaj użytkownika (naprawia FAILED test_user_can_signup_for_trip)
    new_signup = Signup(
        trip_id=trip.id,
        user_id=current_user.id,
        status='oczekuje' # Zgodnie z testem
    )
    db.session.add(new_signup)
    db.session.commit()
    
    flash('Zostałeś zapisany na listę oczekujących.', 'success')
    return redirect(url_for('trips.trip_details', trip_id=trip_id))

@trips_bp.route('/trip/<int:trip_id>/signout', methods=['POST'])
@login_required
def signout_from_trip(trip_id):
    # Ta trasa naprawia FAILED test_user_can_signout_from_trip (błąd 404)
    signup = Signup.query.filter_by(trip_id=trip_id, user_id=current_user.id).first()
    
    if not signup:
        flash('Nie byłeś zapisany na to zlecenie.', 'error')
        return redirect(url_for('trips.trip_details', trip_id=trip_id))

    db.session.delete(signup)
    db.session.commit()
    
    flash('Zostałeś wypisany ze zlecenia.', 'success')
    return redirect(url_for('trips.trip_details', trip_id=trip_id))
